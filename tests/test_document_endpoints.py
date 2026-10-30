"""
tests/test_document_endpoints.py
---------------------------------
Unit and integration tests for new enterprise features:
1. Real-time streaming SSE endpoint (`POST /api/v1/query/stream`)
2. In-database pre-filtered document catalog (`GET /api/v1/documents`)
3. Document ingestion with SHA-256 deduplication gate (`POST /api/v1/documents`)
4. Cascading document deletion (`DELETE /api/v1/documents/{document_id}`)
5. FastMCP `list_documents` tool with role-based access control.
"""

from unittest.mock import AsyncMock, patch, MagicMock
import json
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.manager import DatabaseManager
from app.mcp.gateway import list_documents as mcp_list_documents

client = TestClient(app)


# ---------------------------------------------------------------------------
# Streaming RAG Endpoint Tests
# ---------------------------------------------------------------------------

def test_query_stream_unauthorized_when_require_google_true(monkeypatch):
    """Verify streaming query requires Google ID token when REQUIRE_GOOGLE_AUTH=true."""
    monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "true")
    response = client.post("/api/v1/query/stream", json={"question": "Stream test question?"})
    assert response.status_code == 401
    assert "Authorization header with a Google ID token is required" in response.json()["detail"]


def test_query_stream_sse_successful_flow(monkeypatch):
    """Verify /api/v1/query/stream returns SSE chunks (citations, tokens, done)."""
    monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "false")

    mock_rows = [
        {
            "chunk_id_pk": "chunk-1",
            "document_id": "ENG-2026-105",
            "title": "Public Engineering Guidelines",
            "chunk_index": 0,
            "content": "Engineers must adhere to zero-trust principles.",
            "allowed_roles": ["engineer"],
            "similarity": 0.92,
        }
    ]

    with patch("app.main.generate_embedding", new_callable=AsyncMock) as mock_emb, \
         patch.object(DatabaseManager, "hybrid_search", new_callable=AsyncMock) as mock_search, \
         patch("app.main.chat_completion_stream") as mock_stream:

        mock_emb.return_value = [0.1] * 1536
        mock_search.return_value = mock_rows

        async def token_gen(prompt):
            for word in ["Zero-Trust", " architecture", " verified."]:
                yield word

        mock_stream.side_effect = token_gen

        response = client.post(
            "/api/v1/query/stream",
            json={"question": "What are the engineering guidelines?"},
            headers={"X-User-Roles": '["engineer"]'},
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers["content-type"]

        lines = [line.strip() for line in response.text.split("\n") if line.startswith("data: ")]
        assert len(lines) >= 3  # citations, token(s), done

        events = [json.loads(line.replace("data: ", "")) for line in lines]
        event_types = [e["event"] for e in events]
        assert "citations" in event_types
        assert "token" in event_types
        assert "done" in event_types

        # Verify citation structure
        citation_event = next(e for e in events if e["event"] == "citations")
        assert citation_event["citations"][0]["document_id"] == "ENG-2026-105"


def test_query_stream_empty_roles_returns_refusal(monkeypatch):
    """Verify streaming query returns refusal SSE event when no authorized documents found."""
    monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "false")

    with patch("app.main.generate_embedding", new_callable=AsyncMock) as mock_emb, \
         patch.object(DatabaseManager, "hybrid_search", new_callable=AsyncMock) as mock_search:

        mock_emb.return_value = [0.1] * 1536
        mock_search.return_value = []

        response = client.post(
            "/api/v1/query/stream",
            json={"question": "Confidential data?"},
            headers={"X-User-Roles": '["guest"]'},
        )
        assert response.status_code == 200
        lines = [line.strip() for line in response.text.split("\n") if line.startswith("data: ")]
        events = [json.loads(line.replace("data: ", "")) for line in lines]
        refusal_event = next((e for e in events if e["event"] == "refusal"), None)
        assert refusal_event is not None
        assert "No authorized documentation found" in refusal_event["answer"]


# ---------------------------------------------------------------------------
# Document Catalog & Management Endpoints Tests
# ---------------------------------------------------------------------------

def test_list_documents_empty_roles_returns_empty(monkeypatch):
    """Zero-Trust verification: empty role list returns empty catalog without querying database."""
    monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "false")
    with patch.object(DatabaseManager, "list_documents", new_callable=AsyncMock) as mock_list:
        response = client.get(
            "/api/v1/documents",
            headers={"X-User-Roles": '[]'},
        )
        assert response.status_code == 200
        assert response.json() == []
        mock_list.assert_not_called()


def test_list_documents_returns_catalog(monkeypatch):
    """Verify /api/v1/documents returns pre-filtered documents for verified roles."""
    monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "false")
    mock_docs = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "document_id": "ENG-2026-105",
            "title": "Public Engineering Guidelines",
            "file_hash": "a" * 64,
            "allowed_roles": ["engineer"],
            "chunk_count": 5,
            "created_at": "2026-10-30T12:00:00",
        }
    ]
    with patch.object(DatabaseManager, "list_documents", new_callable=AsyncMock, return_value=mock_docs):
        response = client.get(
            "/api/v1/documents",
            headers={"X-User-Roles": '["engineer"]'},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["document_id"] == "ENG-2026-105"
        assert data[0]["chunk_count"] == 5


def test_ingest_document_deduplication_skip(monkeypatch):
    """Verify document ingestion performs O(1) deduplication skip on identical SHA-256 hash."""
    monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "false")

    with patch.object(DatabaseManager, "get_document_by_hash", new_callable=AsyncMock) as mock_hash_lookup, \
         patch.object(DatabaseManager, "ingest_normalized_document", new_callable=AsyncMock) as mock_ingest:

        mock_hash_lookup.return_value = {
            "document_id": "TEST-DOC-001",
            "title": "Test Title",
        }

        response = client.post(
            "/api/v1/documents",
            json={
                "document_id": "TEST-DOC-001",
                "title": "Test Title",
                "content": "Identical document content for deduplication test.",
                "allowed_roles": ["engineer"],
            },
            headers={"X-User-Roles": '["engineer"]'},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["skipped"] is True
        assert "bypassed via SHA-256" in data["status"]
        mock_ingest.assert_not_called()


def test_delete_document_success(monkeypatch):
    """Verify authorized caller can delete document."""
    monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "false")
    with patch.object(DatabaseManager, "delete_document", new_callable=AsyncMock, return_value=True):
        response = client.delete(
            "/api/v1/documents/ENG-2026-105",
            headers={"X-User-Roles": '["admin"]'},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] is True
        assert data["document_id"] == "ENG-2026-105"


def test_delete_document_forbidden_for_unauthorized_role(monkeypatch):
    """Verify unauthorized role cannot delete documents."""
    monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "false")
    response = client.delete(
        "/api/v1/documents/ENG-2026-105",
        headers={"X-User-Roles": '["compliance_auditor"]'},
    )
    assert response.status_code == 403
    assert "Forbidden" in response.json()["detail"]


# ---------------------------------------------------------------------------
# FastMCP list_documents Tool Tests
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_mcp_list_documents_tool(monkeypatch):
    """Verify FastMCP list_documents tool returns JSON catalog of documents."""
    monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "false")
    mock_docs = [
        {
            "id": "11111111-1111-1111-1111-111111111111",
            "document_id": "DOC-MCP-01",
            "title": "MCP Guide",
            "file_hash": "b" * 64,
            "allowed_roles": ["engineer"],
            "chunk_count": 2,
            "created_at": "2026-10-30T14:00:00",
        }
    ]
    with patch.object(DatabaseManager, "list_documents", new_callable=AsyncMock, return_value=mock_docs):
        result_str = await mcp_list_documents(limit=5, user_roles=["engineer"])
        assert "⛔" not in result_str
        parsed = json.loads(result_str)
        assert parsed["count"] == 1
        assert parsed["documents"][0]["document_id"] == "DOC-MCP-01"
