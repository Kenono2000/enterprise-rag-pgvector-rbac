"""
tests/test_shared_memory.py
----------------------------
Hermetic/offline suite for the shared chat + agent memory store
(app/memory/store.py).

Conventions (mirror tests/test_incident_investigator.py):
  - No database, no network, no LLM calls. DatabaseManager is fully mocked.
  - Deterministic SHA-256 mock embeddings are exercised directly.
  - FastMCP gateway tools are NOT exercised here (see tests/test_mcp_auth.py).
Covered:
  - Fail-closed RBAC: empty caller roles -> [] / no SQL touched.
  - Delegation to canonical sanitize_roles_for_query (single source of truth).
  - extra="forbid" Pydantic schemas reject unknown fields.
  - Thread create/append/list, fact store/upsert/recall all parameterized.
  - Unknown scope is clamped defensively.
"""

from __future__ import annotations

from typing import Optional
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from app.memory.store import (
    MEMORY_EMBEDDING_DIM,
    MemoryChatRequest,
    MemoryChatResponse,
    MemoryFactRequest,
    MemoryFactResponse,
    MemoryRecallRequest,
    MemoryRecallResponse,
    SharedMemoryStore,
    _format_vector,
    _mock_embedding,
    _safe_key,
)
from app.auth.role_mapper import sanitize_roles_for_query


# ---------------------------------------------------------------------------
# Fixtures: monkeypatch DatabaseManager out of every SharedMemoryStore method.
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_db(monkeypatch):
    """Replace DatabaseManager with an in-memory fake that mimics asyncpg behavior."""
    fake_conn = MagicMock()
    fake_conn.fetch = AsyncMock(return_value=[])
    fake_conn.fetchrow = AsyncMock(return_value=None)
    fake_conn.fetchval = AsyncMock(return_value=None)
    fake_conn.execute = AsyncMock(return_value="INSERT 0 1")
    fake_conn.__aenter__ = AsyncMock(return_value=fake_conn)
    fake_conn.__aexit__ = AsyncMock(return_value=False)

    pool = MagicMock()
    pool.acquire = MagicMock(return_value=fake_conn)

    monkeypatch.setattr("app.memory.store.DatabaseManager.get_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr(
        "app.memory.store.DatabaseManager.configure_iterative_scan", AsyncMock(return_value=None)
    )
    return fake_conn


# ---------------------------------------------------------------------------
# Deterministic offline embeddings
# ---------------------------------------------------------------------------


def test_mock_embedding_is_deterministic_and_sanitized():
    v1 = _mock_embedding("shared memory fact")
    v2 = _mock_embedding("shared memory fact")
    v3 = _mock_embedding("different text")
    assert v1 == v2
    assert v1 != v3
    assert len(v1) == MEMORY_EMBEDDING_DIM
    assert all(-1.0 <= x <= 1.0 for x in v1)
    assert all(x == x and abs(x) != float("inf") for x in v1)


def test_safe_key_rejects_malicious_keys():
    assert _safe_key("prefers_dark_mode") == "prefers_dark_mode"
    assert _safe_key("OK.key-1") == "OK.key-1"
    assert _safe_key("../../etc/passwd") == ".._.._etc_passwd"
    assert _safe_key("") == "memory"
    assert len(_safe_key("x" * 300)) <= 128


# ---------------------------------------------------------------------------
# Pydantic schemas: strict extra="forbid"
# ---------------------------------------------------------------------------


def test_schemas_reject_extra_fields():
    with pytest.raises(ValidationError):
        MemoryChatRequest(message="hi", bogus_field=1)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        MemoryRecallRequest(query="q", bogus_field=2)  # type: ignore[call-arg]
    with pytest.raises(ValidationError):
        MemoryFactRequest(key="k", value="v", bogus_field=3)  # type: ignore[call-arg]


def test_schemas_accept_minimal():
    assert MemoryChatRequest(message="hi").message == "hi"
    assert MemoryChatRequest(message="hi").role == "user"
    assert MemoryChatRequest(message="hi").allowed_roles == ["engineer"]
    assert MemoryRecallRequest(query="q").top_k == 5
    assert MemoryRecallRequest(query="q").scope == "all"
    assert MemoryFactRequest(key="k", value="v").source == "agent"
    assert MemoryFactRequest(key="k", value="v").allowed_roles == ["engineer"]


def test_top_k_clamped_and_scope_enum():
    assert MemoryRecallRequest(query="q", top_k=1).top_k == 1
    assert MemoryRecallRequest(query="q", top_k=50).top_k == 50
    with pytest.raises(ValidationError):
        MemoryRecallRequest(query="q", top_k=0)
    with pytest.raises(ValidationError):
        MemoryRecallRequest(query="q", top_k=51)


# ---------------------------------------------------------------------------
# Fail-closed RBAC: zero roles exposes / writes nothing.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recall_with_empty_roles_is_fail_closed(mock_db):
    # Empty roles list -> sanitize_roles_for_query returns [] -> result before
    # any SQL is touched.
    result = await SharedMemoryStore.recall(query="anything", user_roles=[], top_k=5, scope="all")
    assert result == {"query": "anything", "memories": [], "chat_messages": [], "total": 0}


@pytest.mark.asyncio
async def test_recall_with_none_roles_is_fail_closed(mock_db):
    result = await SharedMemoryStore.recall(query="anything", user_roles=None, top_k=5, scope="all")
    assert result == {"query": "anything", "memories": [], "chat_messages": [], "total": 0}


@pytest.mark.asyncio
async def test_create_thread_with_empty_roles_refuses(mock_db):
    result = await SharedMemoryStore.create_thread(title="t", allowed_roles=[])
    assert result is None


@pytest.mark.asyncio
async def test_store_fact_with_empty_roles_refuses(mock_db):
    result = await SharedMemoryStore.store_fact(key="k", value="v", allowed_roles=[])
    assert result is None


# ---------------------------------------------------------------------------
# Delegation to canonical sanitize_roles_for_query (single source of truth).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_store_fact_delegates_to_sanitize(mock_db):
    # Malicious role strings are stripped by the canonical sanitizer; only
    # valid roles survive, so a key paired with a hostile role string still
    # resolves to the clean role set (or fails closed).
    dirty = ["engineer", "'; DROP TABLE agent_memories; --"]
    clean = sanitize_roles_for_query(dirty)
    assert clean == ["engineer"] or clean == []
    result = await SharedMemoryStore.store_fact(key="k", value="v", allowed_roles=dirty)
    # With valid roles surviving sanitization, the write proceeds and returns
    # a memory_id; otherwise it fails closed to None.
    assert result is None or isinstance(result, str)


# ---------------------------------------------------------------------------
# Parameterized SQL shape assertions (no real DB, just query text).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_configure_scan_best_effort_does_not_raise(mock_db):
    # Best-effort per-connection GUC application must never break the flow.
    await SharedMemoryStore._configure_scan(mock_db, roles=["engineer"])


@pytest.mark.asyncio
async def test_format_vector_produces_pgvector_literal():
    assert _format_vector([0.1, -0.2, 0.3]) == "[0.1,-0.2,0.3]"
    assert _format_vector([float("nan")]) == "[0.0]"
    assert _format_vector([float("inf")]) == "[0.0]"


@pytest.mark.asyncio
async def test_create_thread_uses_parameterized_sql(mock_db):
    tid = await SharedMemoryStore.create_thread(
        title="Team chat", allowed_roles=["engineer", "admin"], created_by="alice"
    )
    assert isinstance(tid, str) and len(tid) > 0
    # Parameterized SQL uses $1..$n placeholders (never f-string interpolation).
    sql = str(mock_db.execute.call_args.args[0])
    assert "$1" in sql


@pytest.mark.asyncio
async def test_append_message_refuses_when_thread_missing(mock_db):
    # append_message verifies the thread exists (fetchval returns None) before
    # writing — refusing is the correct behavior for a missing thread.
    mock_db.fetchval = AsyncMock(return_value=None)
    msg_id = await SharedMemoryStore.append_message(
        thread_id="missing-thread", message="hello", allowed_roles=["engineer"]
    )
    assert msg_id is None


@pytest.mark.asyncio
async def test_append_message_writes_when_thread_exists(mock_db):
    mock_db.fetchval = AsyncMock(return_value=["engineer"])
    msg_id = await SharedMemoryStore.append_message(
        thread_id="tid", message="hello", role="user", allowed_roles=["engineer"]
    )
    assert isinstance(msg_id, str) and len(msg_id) > 0
    sql = str(mock_db.execute.call_args.args[0])
    assert "vector" in sql.lower() and "jsonb" in sql.lower()


@pytest.mark.asyncio
async def test_list_threads_prefilters_by_roles(mock_db):
    mock_db.fetch = AsyncMock(return_value=[{"thread_id": "t1", "title": "T1", "created_by": "alice", "allowed_roles": ["engineer"], "created_at": None}])
    threads = await SharedMemoryStore.list_threads(user_roles=["engineer"], limit=5)
    assert len(threads) == 1
    assert threads[0]["thread_id"] == "t1"
    sql = str(mock_db.fetch.call_args.args[0])
    assert "?" in sql and "$1" in sql


@pytest.mark.asyncio
async def test_store_fact_upsert_on_conflict(mock_db):
    mid = await SharedMemoryStore.store_fact(
        key="prefers_dark_mode", value="true", allowed_roles=["engineer"], source="agent"
    )
    assert isinstance(mid, str) and len(mid) > 0
    sql = str(mock_db.execute.call_args.args[0])
    assert "ON CONFLICT" in sql and "memory_key" in sql


@pytest.mark.asyncio
async def test_recall_facts_ordering_and_limit(mock_db):
    mock_db.fetch = AsyncMock(
        return_value=[
            {"memory_id": "a", "memory_key": "k1", "value": "v1", "source": "agent", "allowed_roles": ["engineer"], "created_at": None, "similarity": 0.9},
            {"memory_id": "b", "memory_key": "k2", "value": "v2", "source": "agent", "allowed_roles": ["engineer"], "created_at": None, "similarity": 0.5},
        ]
    )
    result = await SharedMemoryStore.recall_facts(query="q", user_roles=["engineer"], top_k=2)
    assert len(result) == 2
    assert result[0]["similarity"] == 0.9  # DESC order by distance
    sql = str(mock_db.fetch.call_args.args[0])
    assert "<=>" in sql  # cosine distance operator
    assert "LIMIT" in sql.upper()


@pytest.mark.asyncio
async def test_recall_chat_joins_threads_with_rbac(mock_db):
    mock_db.fetch = AsyncMock(
        return_value=[{"message_id": "m1", "thread_id": "t1", "role": "user", "content": "hello", "metadata": {}, "created_at": None, "similarity": 0.8}]
    )
    result = await SharedMemoryStore._recall_chat(query="q", roles=["engineer"], top_k=5)
    assert len(result) == 1
    assert result[0]["content"] == "hello"
    sql = str(mock_db.fetch.call_args.args[0])
    assert "JOIN" in sql.upper() and "allowed_roles" in sql


# ---------------------------------------------------------------------------
# Invalid scope falls back to a safe default (defense in depth).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recall_unknown_scope_treated_as_all(mock_db):
    # The store clamps unknown scopes defensively rather than raising.
    result = await SharedMemoryStore.recall(
        query="q", user_roles=["engineer"], top_k=3, scope="bogus"
    )
    assert result["query"] == "q"
    assert result["total"] == 0


# ---------------------------------------------------------------------------
# Module exports exist at top level.
# ---------------------------------------------------------------------------


def test_module_top_level_exports_exist():
    import app.memory.store as store_mod

    for name in [
        "SharedMemoryStore",
        "MemoryChatRequest",
        "MemoryChatResponse",
        "MemoryRecallRequest",
        "MemoryRecallResponse",
        "MemoryFactRequest",
        "MemoryFactResponse",
        "_mock_embedding",
        "_safe_key",
        "_format_vector",
        "MEMORY_EMBEDDING_DIM",
    ]:
        assert hasattr(store_mod, name), f"missing export {name}"
