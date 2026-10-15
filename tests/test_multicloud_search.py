"""
tests/test_multicloud_search.py
-------------------------------
Unit and regression tests for Google Cloud (Vertex AI) and Databricks (Mosaic AI)
search integration, Zero-Trust RBAC filter construction, and dynamic multi-cloud routing.
"""
from __future__ import annotations

import os
import json
from unittest.mock import patch, AsyncMock, MagicMock
import pytest
from fastapi.testclient import TestClient

from app.db.gcp_search import gcp_hybrid_search
from app.db.databricks_search import databricks_hybrid_search
from app.main import app

client = TestClient(app)


# ==============================================================================
# Google Cloud Vertex AI Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_gcp_hybrid_search_empty_roles_returns_empty():
    """Zero-Trust verification: If user has no roles, search terminates immediately."""
    result = await gcp_hybrid_search(
        query_text="Confidential Infrastructure",
        query_vector=[0.1] * 1536,
        user_roles=[],
        limit=3,
    )
    assert result == []


@pytest.mark.asyncio
async def test_gcp_hybrid_search_executes_with_restricts():
    """Verify that Vertex AI Vector Search executes with properly constructed restricts clause."""
    mock_client = AsyncMock()
    mock_client.find_neighbors.return_value = [
        {
            "id": "gcp-chunk-1",
            "similarity": 0.95,
            "metadata": {
                "document_id": "doc-gcp-101",
                "title": "Google Cloud Architecture",
                "content": "Vertex AI Vector Search with ScaNN.",
                "chunk_index": 0,
                "allowed_roles": ["engineer"],
            },
        }
    ]

    with patch("app.db.gcp_search.get_gcp_vector_client", return_value=mock_client):
        results = await gcp_hybrid_search(
            query_text="Vertex AI architecture",
            query_vector=[0.1] * 1536,
            user_roles=["engineer", "architect"],
            limit=3,
        )

        assert len(results) == 1
        assert results[0]["document_id"] == "doc-gcp-101"
        assert results[0]["title"] == "Google Cloud Architecture"
        assert results[0]["similarity"] == 0.95

        # Verify Restricts clause
        call_kwargs = mock_client.find_neighbors.call_args.kwargs
        assert "restricts" in call_kwargs
        expected_restricts = [
            {
                "namespace": "allowed_roles",
                "allowList": ["engineer", "architect"],
            }
        ]
        assert call_kwargs["restricts"] == expected_restricts


# ==============================================================================
# Databricks Mosaic AI Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_databricks_hybrid_search_empty_roles_returns_empty():
    """Zero-Trust verification: If user has no roles, search terminates immediately."""
    result = await databricks_hybrid_search(
        query_text="Financial Forecast",
        query_vector=[0.1] * 1536,
        user_roles=[],
        limit=3,
    )
    assert result == []


@pytest.mark.asyncio
async def test_databricks_hybrid_search_executes_with_filters():
    """Verify that Databricks Vector Search executes with proper Unity Catalog filters."""
    mock_client = AsyncMock()
    mock_client.query_index.return_value = [
        {
            "row": {
                "id": "dbx-chunk-1",
                "document_id": "doc-dbx-202",
                "title": "Databricks Delta Spec",
                "content": "Mosaic AI Vector Search over Delta Lake.",
                "chunk_index": 0,
                "allowed_roles": ["engineer"],
            },
            "score": 0.92,
        }
    ]

    with patch("app.db.databricks_search.get_databricks_vector_client", return_value=mock_client):
        results = await databricks_hybrid_search(
            query_text="Delta Lake specifications",
            query_vector=[0.1] * 1536,
            user_roles=["engineer"],
            limit=3,
        )

        assert len(results) == 1
        assert results[0]["document_id"] == "doc-dbx-202"
        assert results[0]["title"] == "Databricks Delta Spec"
        assert results[0]["similarity"] == 0.92

        # Verify filters_json
        call_kwargs = mock_client.query_index.call_args.kwargs
        assert "filters_json" in call_kwargs
        filter_obj = json.loads(call_kwargs["filters_json"])
        assert filter_obj == {"allowed_roles": "engineer"}


# ==============================================================================
# Dynamic Backend Dispatch Tests (POST /api/v1/query)
# ==============================================================================

def test_main_query_routes_to_gcp_when_configured(monkeypatch):
    """Verify that POST /api/v1/query dispatches to GCP when RETRIEVAL_BACKEND='gcp'."""
    monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "false")
    monkeypatch.setenv("RETRIEVAL_BACKEND", "gcp")

    with patch("app.main.generate_embedding", new_callable=AsyncMock) as mock_emb, \
         patch("app.db.gcp_search.gcp_hybrid_search", new_callable=AsyncMock) as mock_gcp_search, \
         patch("app.main.chat_completion", new_callable=AsyncMock) as mock_llm:

        mock_emb.return_value = [0.1] * 1536
        mock_gcp_search.return_value = [
            {
                "document_id": "gcp-doc-1",
                "title": "Google Cloud Reference",
                "content": "Vertex AI Vector Search content.",
                "chunk_index": 0,
                "allowed_roles": ["engineer"],
                "similarity": 0.94,
            }
        ]
        mock_llm.return_value = "Vertex AI integration is active."

        response = client.post(
            "/api/v1/query",
            json={"question": "Tell me about Vertex AI search."},
            headers={"X-User-Roles": '["engineer"]'},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["answer"] == "Vertex AI integration is active."
        assert len(data["citations"]) == 1
        assert data["citations"][0]["document_id"] == "gcp-doc-1"
        assert mock_gcp_search.called


def test_main_query_routes_to_databricks_when_configured(monkeypatch):
    """Verify that POST /api/v1/query dispatches to Databricks when RETRIEVAL_BACKEND='databricks'."""
    monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "false")
    monkeypatch.setenv("RETRIEVAL_BACKEND", "databricks")

    with patch("app.main.generate_embedding", new_callable=AsyncMock) as mock_emb, \
         patch("app.db.databricks_search.databricks_hybrid_search", new_callable=AsyncMock) as mock_dbx_search, \
         patch("app.main.chat_completion", new_callable=AsyncMock) as mock_llm:

        mock_emb.return_value = [0.1] * 1536
        mock_dbx_search.return_value = [
            {
                "document_id": "dbx-doc-1",
                "title": "Databricks Reference",
                "content": "Mosaic AI Vector Search content.",
                "chunk_index": 0,
                "allowed_roles": ["engineer"],
                "similarity": 0.91,
            }
        ]
        mock_llm.return_value = "Databricks Mosaic AI is active."

        response = client.post(
            "/api/v1/query",
            json={"question": "Tell me about Databricks Mosaic search."},
            headers={"X-User-Roles": '["engineer"]'},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["answer"] == "Databricks Mosaic AI is active."
        assert len(data["citations"]) == 1
        assert data["citations"][0]["document_id"] == "dbx-doc-1"
        assert mock_dbx_search.called


# ==============================================================================
# FastMCP Gateway Routing Tests
# ==============================================================================

@pytest.mark.asyncio
async def test_mcp_gateway_routes_to_gcp(monkeypatch):
    """Verify FastMCP search_sdlc_context tool routes to GCP when RETRIEVAL_BACKEND='gcp'."""
    from app.mcp.gateway import search_sdlc_context
    monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "false")
    monkeypatch.setenv("RETRIEVAL_BACKEND", "gcp")

    with patch("app.mcp.gateway.generate_embedding", new_callable=AsyncMock) as mock_emb, \
         patch("app.db.gcp_search.gcp_hybrid_search", new_callable=AsyncMock) as mock_gcp_search, \
         patch("app.mcp.gateway.chat_completion", new_callable=AsyncMock) as mock_llm:

        mock_emb.return_value = [0.1] * 1536
        mock_gcp_search.return_value = [
            {
                "document_id": "gcp-doc-1",
                "title": "GCP Standards",
                "content": "Google Cloud security standards.",
                "chunk_index": 0,
                "allowed_roles": ["engineer"],
                "similarity": 0.97,
            }
        ]
        mock_llm.return_value = "Follow GCP security standards."

        result = await search_sdlc_context(
            question="What are GCP standards?",
            user_roles=["engineer"],
        )

        assert "Follow GCP security standards." in result
        assert "GCP Standards" in result
        assert mock_gcp_search.called


@pytest.mark.asyncio
async def test_mcp_gateway_routes_to_databricks(monkeypatch):
    """Verify FastMCP search_sdlc_context tool routes to Databricks when RETRIEVAL_BACKEND='databricks'."""
    from app.mcp.gateway import search_sdlc_context
    monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "false")
    monkeypatch.setenv("RETRIEVAL_BACKEND", "databricks")

    with patch("app.mcp.gateway.generate_embedding", new_callable=AsyncMock) as mock_emb, \
         patch("app.db.databricks_search.databricks_hybrid_search", new_callable=AsyncMock) as mock_dbx_search, \
         patch("app.mcp.gateway.chat_completion", new_callable=AsyncMock) as mock_llm:

        mock_emb.return_value = [0.1] * 1536
        mock_dbx_search.return_value = [
            {
                "document_id": "dbx-doc-1",
                "title": "Databricks Governance",
                "content": "Unity Catalog access control policies.",
                "chunk_index": 0,
                "allowed_roles": ["engineer"],
                "similarity": 0.93,
            }
        ]
        mock_llm.return_value = "Unity catalog policies are enforced."

        result = await search_sdlc_context(
            question="What are Databricks policies?",
            user_roles=["engineer"],
        )

        assert "Unity catalog policies are enforced." in result
        assert "Databricks Governance" in result
        assert mock_dbx_search.called

