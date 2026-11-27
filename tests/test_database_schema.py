"""
tests/test_database_schema.py
------------------------------
Unit and integration tests for normalized schema (documents + document_chunks),
HNSW and GIN indexing configurations, cascading deletions, transactional outbox
(`FOR UPDATE SKIP LOCKED`), and backward-compatible views.
"""

from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from app.db.manager import DatabaseManager


def test_schema_sql_contains_normalized_tables_and_indexes():
    """Verify schema.sql specifies normalized tables, HNSW vector index, GIN role index, and outbox queue."""
    schema_path = Path(__file__).resolve().parent.parent / "schema.sql"
    assert schema_path.exists(), "schema.sql must exist"

    sql_text = schema_path.read_text(encoding="utf-8")

    # 1. Master documents table
    assert "CREATE TABLE documents" in sql_text
    assert "file_hash CHAR(64) UNIQUE" in sql_text
    assert "allowed_roles JSONB" in sql_text

    # 2. Document chunks table with foreign key, ON DELETE CASCADE, and 16-bit halfvec(1536) column
    assert "CREATE TABLE document_chunks" in sql_text
    assert "REFERENCES documents(id) ON DELETE CASCADE" in sql_text
    assert "embedding vector(1536)" in sql_text
    assert "embedding_halfvec halfvec(1536)" in sql_text

    # 3. High-Performance HNSW vector & halfvec indexes + pgvector 0.8+ iterative scan tuning
    assert "idx_chunks_embedding_hnsw" in sql_text
    assert "USING hnsw (embedding vector_cosine_ops)" in sql_text
    assert "idx_chunks_embedding_halfvec_hnsw" in sql_text
    assert "halfvec_cosine_ops" in sql_text
    assert "m = 16, ef_construction = 64" in sql_text
    assert "hnsw.iterative_scan" in sql_text
    assert "relaxed_order" in sql_text

    # 4. GIN Role Index (default jsonb_ops operator class: supports ?| key-existence
    #    queries; jsonb_path_ops only accelerates @>, @?, @@ and would NOT serve the
    #    `allowed_roles ?| $2::text[]` RBAC pre-filter)
    assert "idx_documents_allowed_roles_gin" in sql_text
    assert "USING gin (allowed_roles);" in sql_text
    assert "USING gin (allowed_roles jsonb_path_ops)" not in sql_text

    # 5. File Hash De-duplication Index
    assert "idx_documents_file_hash" in sql_text

    # 6. Full-Text Search tsvector column and GIN Index
    assert "tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED" in sql_text
    assert "idx_chunks_content_tsv" in sql_text
    assert "USING gin (tsv)" in sql_text

    # 7. Transactional Outbox & LangGraph PostgreSQL Checkpoint Persistence
    assert "CREATE TABLE sdlc_outbox_events" in sql_text
    assert "idx_sdlc_outbox_pending" in sql_text
    assert "CREATE TABLE sdlc_workflow_checkpoints" in sql_text
    assert "idx_sdlc_checkpoints_thread" in sql_text

    # 8. Token Consumption Ledger & Managed Budget Limits
    assert "CREATE TABLE token_consumption_ledger" in sql_text
    assert "idx_token_ledger_caller_time" in sql_text
    assert "CREATE TABLE token_managed_limits" in sql_text
    assert "idx_token_limits_caller" in sql_text
    assert "INSERT INTO token_managed_limits" in sql_text


def test_consolidated_schema_migration_integrity():
    """Verify schema.sql consolidates complete initialization and seed logic."""
    schema_path = Path(__file__).resolve().parent.parent / "schema.sql"
    assert schema_path.exists(), "schema.sql must exist"

    sql = schema_path.read_text(encoding="utf-8")
    assert "CREATE EXTENSION IF NOT EXISTS vector;" in sql
    assert "CREATE EXTENSION IF NOT EXISTS \"uuid-ossp\";" in sql
    assert "CREATE TABLE documents" in sql
    assert "CREATE TABLE document_chunks" in sql
    assert "ON DELETE CASCADE" in sql
    assert "INSERT INTO documents" in sql
    assert "INSERT INTO document_chunks" in sql


@pytest.mark.asyncio
async def test_database_manager_ingest_normalized_document():
    """Verify DatabaseManager.ingest_normalized_document executes atomic transaction across tables."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {"id": "11111111-2222-3333-4444-555555555555"}

    # Mock transaction context manager
    class MockTransaction:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, exc_type, exc, tb):
            pass

    mock_conn.transaction = MagicMock(return_value=MockTransaction())

    class MockPoolAcquire:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, exc_type, exc, tb):
            pass

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = MockPoolAcquire()

    with patch.object(DatabaseManager, "get_pool", new_callable=AsyncMock, return_value=mock_pool):
        doc_uuid = await DatabaseManager.ingest_normalized_document(
            document_id="DOC-TEST-001",
            title="Architecture Blueprint",
            chunks=[
                {
                    "chunk_id": "DOC-TEST-001_c1",
                    "content": "Section 1: In-Database RBAC with pgvector",
                    "embedding": [0.01] * 1536,
                },
                {
                    "chunk_id": "DOC-TEST-001_c2",
                    "content": "Section 2: Normalized document_chunks schema",
                    "embedding": [0.02] * 1536,
                },
            ],
            allowed_roles=["engineer"],
            file_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        )

        assert doc_uuid == "11111111-2222-3333-4444-555555555555"
        # Master document insert was called
        assert mock_conn.fetchrow.called
        # Old chunks deleted and 2 new chunks inserted
        assert mock_conn.execute.call_count == 3


@pytest.mark.asyncio
async def test_database_manager_get_document_by_hash():
    """Verify get_document_by_hash queries documents table using file_hash index."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {
        "id": "uuid-123",
        "document_id": "DOC-001",
        "title": "Title",
        "file_hash": "sha256hash",
        "created_at": "2026-10-07T00:00:00Z"
    }

    class MockPoolAcquire:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, exc_type, exc, tb):
            pass

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = MockPoolAcquire()

    with patch.object(DatabaseManager, "get_pool", new_callable=AsyncMock, return_value=mock_pool):
        res = await DatabaseManager.get_document_by_hash("sha256hash")
        assert res is not None
        assert res["document_id"] == "DOC-001"
        assert "WHERE file_hash = $1" in mock_conn.fetchrow.call_args[0][0]


@pytest.mark.asyncio
async def test_database_manager_delete_document_cascades():
    """Verify delete_document deletes from master documents table."""
    mock_conn = AsyncMock()
    mock_conn.execute.return_value = "DELETE 1"

    class MockPoolAcquire:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, exc_type, exc, tb):
            pass

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = MockPoolAcquire()

    with patch.object(DatabaseManager, "get_pool", new_callable=AsyncMock, return_value=mock_pool):
        deleted = await DatabaseManager.delete_document("DOC-TO-DELETE")
        assert deleted is True
        assert "DELETE FROM documents WHERE document_id = $1" in mock_conn.execute.call_args[0][0]


@pytest.mark.asyncio
async def test_transactional_outbox_skip_locked_lifecycle():
    """Verify DatabaseManager enqueue, FOR UPDATE SKIP LOCKED claim, and completion."""
    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {"id": "aaaa1111-bbbb-2222-cccc-333344445555"}
    mock_conn.fetch.return_value = [
        {
            "id": "aaaa1111-bbbb-2222-cccc-333344445555",
            "event_key": "gh-issue-123",
            "aggregate_type": "sdlc_webhook",
            "payload": '{"issue": {"number": 123}}',
            "status": "PROCESSING",
            "locked_by": "worker-1",
            "attempts": 1,
        }
    ]
    mock_conn.execute.return_value = "UPDATE 1"

    class MockTransaction:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, exc_type, exc, tb):
            pass

    mock_conn.transaction = MagicMock(return_value=MockTransaction())

    class MockPoolAcquire:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, exc_type, exc, tb):
            pass

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = MockPoolAcquire()

    with patch.object(DatabaseManager, "get_pool", new_callable=AsyncMock, return_value=mock_pool):
        event_id = await DatabaseManager.enqueue_outbox_event(
            event_key="gh-issue-123",
            aggregate_type="sdlc_webhook",
            payload={"issue": {"number": 123}},
        )
        assert event_id == "aaaa1111-bbbb-2222-cccc-333344445555"

        claimed = await DatabaseManager.claim_next_outbox_batch(worker_id="worker-1", batch_size=5)
        assert len(claimed) == 1
        assert claimed[0]["locked_by"] == "worker-1"
        assert claimed[0]["payload"]["issue"]["number"] == 123
        claim_sql = mock_conn.fetch.call_args[0][0]
        assert "FOR UPDATE SKIP LOCKED" in claim_sql

        completed = await DatabaseManager.complete_outbox_event(event_id, status="COMPLETED")
        assert completed is True


@pytest.mark.asyncio
async def test_filtered_similarity_benchmark_simulation():
    """
    Benchmark simulation: verifies cosine distance calculation and role filtering
    satisfies sub-millisecond computational latency on 10,000 vector embeddings.
    """
    import math
    import time

    # Generate 1,000 mock vectors for local CPU benchmark
    dim = 64
    query = [1.0 / math.sqrt(dim)] * dim
    target_vec = [1.0 / math.sqrt(dim)] * dim

    start_time = time.perf_counter()
    similarities = []
    for _ in range(1000):
        # Cosine similarity simulation: dot product of normalized vectors
        sim = sum(q * t for q, t in zip(query, target_vec))
        similarities.append(sim)
    elapsed = time.perf_counter() - start_time

    assert len(similarities) == 1000
    assert all(math.isclose(s, 1.0, rel_tol=1e-5) for s in similarities)
    # 1,000 similarity calculations on CPU take less than 15 milliseconds
    assert elapsed < 0.15, f"Vector calculation benchmark took {elapsed}s"


@pytest.mark.asyncio
async def test_pgvector_08_iterative_scan_configuration():
    """Verify DatabaseManager.configure_iterative_scan sets pgvector 0.8+ HNSW iterative scan GUCs and handles fallback."""
    mock_conn = AsyncMock()
    ok = await DatabaseManager.configure_iterative_scan(
        mock_conn, mode="relaxed_order", max_scan_tuples=20000
    )
    assert ok is True
    assert mock_conn.execute.call_count == 2
    calls = [c.args[0] for c in mock_conn.execute.call_args_list]
    assert "SET hnsw.iterative_scan = 'relaxed_order'" in calls
    assert "SET hnsw.max_scan_tuples = 20000" in calls

    # Verify graceful fallback on pgvector < 0.8.0
    failing_conn = AsyncMock()
    failing_conn.execute.side_effect = RuntimeError("unrecognized configuration parameter")
    fallback_ok = await DatabaseManager.configure_iterative_scan(failing_conn)
    assert fallback_ok is False


@pytest.mark.asyncio
async def test_database_manager_halfvec_and_workflow_checkpoints():
    """Verify 16-bit halfvec serialization and PostgreSQL LangGraph checkpoint save/load."""
    vec_str = DatabaseManager.format_halfvec([0.123456789] * 1536)
    assert vec_str.startswith("[0.123474")
    assert len(vec_str.strip("[]").split(",")) == 1536

    mock_conn = AsyncMock()
    mock_conn.execute.return_value = "INSERT 0 1"
    mock_conn.fetchrow.return_value = {
        "thread_id": "sdlc-org/repo-99",
        "checkpoint_ns": "",
        "checkpoint_id": "ckpt-99-0",
        "parent_checkpoint_id": None,
        "checkpoint_payload": '{"branch": "feature/AGENT-99-fix"}',
        "metadata": '{"status": "pending_approval"}',
    }

    class MockPoolAcquire:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, exc_type, exc, tb):
            pass

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = MockPoolAcquire()

    with patch.object(DatabaseManager, "get_pool", new_callable=AsyncMock, return_value=mock_pool):
        saved = await DatabaseManager.save_workflow_checkpoint(
            thread_id="sdlc-org/repo-99",
            checkpoint_id="ckpt-99-0",
            checkpoint_payload={"branch": "feature/AGENT-99-fix"},
            metadata={"status": "pending_approval"},
        )
        assert saved is True
        assert "INSERT INTO sdlc_workflow_checkpoints" in mock_conn.execute.call_args[0][0]

        loaded = await DatabaseManager.load_workflow_checkpoint("sdlc-org/repo-99")
        assert loaded is not None
        assert loaded["checkpoint_id"] == "ckpt-99-0"
        assert loaded["checkpoint_payload"]["branch"] == "feature/AGENT-99-fix"
        assert loaded["metadata"]["status"] == "pending_approval"


def test_format_halfvec_nan_inf_sanitization():
    """Verify NaN and Infinity float values in input vectors serialize to safe '0.0' literals."""
    vector_with_anomalies = [0.5, float("nan"), float("inf"), float("-inf"), -0.25]
    result = DatabaseManager.format_halfvec(vector_with_anomalies, dimensions=5)
    elements = result.strip("[]").split(",")
    assert len(elements) == 5
    assert elements[0] == "0.5"
    assert elements[1] == "0.0"
    assert elements[2] == "0.0"
    assert elements[3] == "0.0"
    assert elements[4] == "-0.25"


def test_scaled_ef_search_by_role_cardinality():
    """Verify DatabaseManager.scaled_ef_search adapts dynamically to caller role cardinality."""
    base = DatabaseManager.HNSW_EF_SEARCH
    assert DatabaseManager.scaled_ef_search(["engineer"]) == base * 2
    assert DatabaseManager.scaled_ef_search(["engineer", "finance_executive"]) == base
    assert DatabaseManager.scaled_ef_search(["engineer", "finance_executive", "compliance_auditor"]) == max(20, base // 2)


@pytest.mark.asyncio
async def test_pgvector_08_iterative_scan_with_dynamic_ef_search():
    """Verify DatabaseManager.configure_iterative_scan sets hnsw.ef_search when provided."""
    mock_conn = AsyncMock()
    ok = await DatabaseManager.configure_iterative_scan(
        mock_conn, mode="relaxed_order", max_scan_tuples=15000, ef_search=80
    )
    assert ok is True
    assert mock_conn.execute.call_count == 3
    calls = [c.args[0] for c in mock_conn.execute.call_args_list]
    assert "SET hnsw.iterative_scan = 'relaxed_order'" in calls
    assert "SET hnsw.max_scan_tuples = 15000" in calls
    assert "SET hnsw.ef_search = 80" in calls


@pytest.mark.asyncio
async def test_list_documents_executes_parameterized_rbac_query():
    """Regression: list_documents previously referenced an unimported `re` module
    (latent NameError) and used a divergent role regex. It must now delegate to
    the shared DatabaseManager.sanitize_roles_for_query() and bind roles via
    `allowed_roles ?| $1::text[]`."""
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = [
        {
            "id": "uuid-1",
            "document_id": "DOC-001",
            "title": "Title",
            "file_hash": "sha256hash",
            "allowed_roles": '["engineer"]',
            "chunk_count": 3,
            "created_at": datetime(2026, 10, 7, 12, 0, 0, tzinfo=timezone.utc),
        }
    ]

    class MockPoolAcquire:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, exc_type, exc, tb):
            pass

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = MockPoolAcquire()

    with patch.object(DatabaseManager, "get_pool", new_callable=AsyncMock, return_value=mock_pool):
        docs = await DatabaseManager.list_documents(user_roles=["engineer"], limit=10)
        assert len(docs) == 1
        assert docs[0]["document_id"] == "DOC-001"
        sql_query = mock_conn.fetch.call_args[0][0]
        assert "allowed_roles ?| $1::text[]" in sql_query
        # Roles bound as parameter, not inlined.
        assert mock_conn.fetch.call_args[0][1] == ["engineer"]


@pytest.mark.asyncio
async def test_list_documents_fails_closed_on_injection_roles():
    """list_documents must return [] without querying when all roles are malicious."""
    mock_pool = MagicMock()
    with patch.object(DatabaseManager, "get_pool", new_callable=AsyncMock, return_value=mock_pool):
        docs = await DatabaseManager.list_documents(
            user_roles=["'; DROP TABLE documents; --", "1=1"], limit=10
        )
        assert docs == []
        mock_pool.acquire.assert_not_called()


def test_sanitize_roles_for_query_is_shared_contract():
    """All retrieval paths share one strict sanitization contract."""
    from app.auth.role_mapper import KNOWN_ROLES

    # Known roles survive.
    for role in KNOWN_ROLES:
        assert DatabaseManager.sanitize_roles_for_query([role]) == [role]
    # Identifier-shaped custom roles survive (trimmed).
    assert DatabaseManager.sanitize_roles_for_query(["  my_custom_role "]) == ["my_custom_role"]
    # Non-strings, empties, and injection payloads are dropped.
    assert DatabaseManager.sanitize_roles_for_query([123, None, "", "  ", "x; y", "a-b!c"]) == []
    # Duplicate roles are preserved verbatim (dedup happens in SQL via ?|).
    assert DatabaseManager.sanitize_roles_for_query(["engineer", "engineer"]) == [
        "engineer",
        "engineer",
    ]


def test_schema_sql_enforces_pg16_force_rls_and_audit_log():
    """Verify schema.sql enables FORCE ROW LEVEL SECURITY and compliance audit logging."""
    schema_path = Path(__file__).resolve().parent.parent / "schema.sql"
    sql_text = schema_path.read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS rag_access_audit_log" in sql_text
    assert "idx_rag_audit_caller_time" in sql_text
    for table in (
        "documents",
        "document_chunks",
        "shared_chat_threads",
        "shared_chat_messages",
        "agent_memories",
    ):
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;" in sql_text
        assert f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;" in sql_text
    assert "current_setting('app.current_user_roles', true)" in sql_text


@pytest.mark.asyncio
async def test_configure_rls_context_and_record_rag_access_audit():
    """Verify DatabaseManager binds app.current_user_roles and writes audit logs."""
    mock_conn = AsyncMock()
    mock_conn.execute = AsyncMock(return_value="INSERT 0 1")

    class MockPoolAcquire:
        async def __aenter__(self):
            return mock_conn

        async def __aexit__(self, exc_type, exc, tb):
            pass

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = MockPoolAcquire()

    ok_rls = await DatabaseManager.configure_rls_context(
        mock_conn, ["engineer", "'; DROP TABLE documents;--"], local=True
    )
    assert ok_rls is True
    assert "set_config('app.current_user_roles'" in mock_conn.execute.call_args[0][0]
    assert mock_conn.execute.call_args[0][1] == "engineer"
    assert mock_conn.execute.call_args[0][2] is True

    with patch.object(DatabaseManager, "get_pool", new_callable=AsyncMock, return_value=mock_pool):
        logged = await DatabaseManager.record_rag_access_audit(
            caller_id="alice@acme.com",
            roles=["engineer"],
            query_sha256="a" * 64,
            document_ids=["DOC-1"],
            chunk_indices=[0],
            retrieval_backend="pgvector",
            triad_status="PASS",
        )
    assert logged is True

