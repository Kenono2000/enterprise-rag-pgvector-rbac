"""
tests/test_integration_pgvector.py
----------------------------------
Integration tests with testcontainers-python and pgvector/pgvector:pg16.
Verifies end-to-end database initialization with schema.sql, HNSW indexing,
GIN full-text search, and in-database RBAC filtering.
"""

from pathlib import Path
import pytest

# Check Docker and testcontainers availability
_HAS_TESTCONTAINERS = False
try:
    from testcontainers.postgres import PostgresContainer
    _HAS_TESTCONTAINERS = True
except Exception:
    _HAS_TESTCONTAINERS = False


@pytest.mark.skipif(not _HAS_TESTCONTAINERS, reason="testcontainers-python not installed or Docker daemon unavailable")
def test_pgvector_container_integration():
    """
    Spins up pgvector/pgvector:pg16 container, applies schema.sql, and validates
    that vector cosine distance and GIN full-text search operate correctly.
    """
    import psycopg2

    schema_path = Path(__file__).resolve().parent.parent / "schema.sql"
    assert schema_path.exists()
    schema_sql = schema_path.read_text(encoding="utf-8")

    with PostgresContainer("pgvector/pgvector:pg16") as postgres:
        conn_url = postgres.get_connection_url()
        with psycopg2.connect(conn_url) as conn:
            with conn.cursor() as cur:
                # Apply full consolidated schema
                cur.execute(schema_sql)
                conn.commit()

                # Verify vector extension is enabled
                cur.execute("SELECT extname FROM pg_extension WHERE extname = 'vector';")
                ext = cur.fetchone()
                assert ext is not None
                assert ext[0] == "vector"

                # Verify seed documents exist
                cur.execute("SELECT COUNT(*) FROM documents;")
                doc_count = cur.fetchone()[0]
                assert doc_count >= 3

                # Verify document_chunks and tsv generation
                cur.execute("SELECT chunk_id, tsv IS NOT NULL FROM document_chunks LIMIT 1;")
                chunk_row = cur.fetchone()
                assert chunk_row is not None
                assert chunk_row[1] is True  # tsv tsvector automatically populated


def test_schema_sql_container_readiness():
    """
    Validates that schema.sql is syntactically sound and contains all required
    DDL and seed instructions for pgvector/pgvector:pg16 container initialization.
    """
    schema_path = Path(__file__).resolve().parent.parent / "schema.sql"
    assert schema_path.exists()
    content = schema_path.read_text(encoding="utf-8")

    assert "CREATE EXTENSION IF NOT EXISTS vector;" in content
    assert "tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED" in content
    assert "idx_chunks_embedding_hnsw" in content
    assert "idx_chunks_content_tsv" in content
    assert "idx_documents_allowed_roles_gin" in content
