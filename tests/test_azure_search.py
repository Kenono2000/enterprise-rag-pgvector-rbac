"""
tests/test_azure_search.py
--------------------------
Unit and regression tests for Azure AI Search backend integration,
Zero-Trust RBAC OData filter construction, and dual-backend routing.
"""
from __future__ import annotations

import os
from unittest.mock import patch, AsyncMock, MagicMock
import pytest
from fastapi.testclient import TestClient

from app.db.azure_search import azure_hybrid_search
from app.main import app

client = TestClient(app)


@pytest.mark.asyncio
async def test_azure_hybrid_search_empty_roles_returns_empty():
    """Zero-Trust verification: If user has no roles, search terminates immediately."""
    result = await azure_hybrid_search(
        query_text="Confidential Strategy",
        query_vector=[0.1] * 1536,
        user_roles=[],
        limit=3,
    )
    assert result == []


@pytest.mark.asyncio
async def test_azure_hybrid_search_executes_with_rbac_filter():
    """Verify that Azure AI Search executes with properly constructed OData filter."""
    dummy_item = {
        "id": "chunk-123",
        "document_id": "doc-eng-1",
        "title": "Cloud Architecture Spec",
        "content": "Zero-trust principles apply.",
        "chunk_index": 0,
        "allowed_roles": ["engineer"],
        "@search.reranker_score": 3.85,
    }

    async def mock_search_results():
        yield dummy_item

    mock_client = AsyncMock()
    mock_client.search.return_value = mock_search_results()

    with patch("app.db.azure_search.get_search_client", return_value=mock_client):
        results = await azure_hybrid_search(
            query_text="Zero-trust principles",
            query_vector=[0.1] * 1536,
            user_roles=["engineer", "architect"],
            limit=3,
        )

        assert len(results) == 1
        assert results[0]["document_id"] == "doc-eng-1"
        assert results[0]["title"] == "Cloud Architecture Spec"
        assert results[0]["similarity"] == 3.85

        # Verify OData filter clause was properly built
        call_kwargs = mock_client.search.call_args.kwargs
        assert "filter" in call_kwargs
        expected_filter = "allowed_roles/any(r: r eq 'engineer' or r eq 'architect')"
        assert call_kwargs["filter"] == expected_filter
        assert call_kwargs["query_type"] == "semantic"


def test_main_query_routes_to_azure_when_configured(monkeypatch):
    """Verify that POST /api/v1/query dispatches to Azure AI Search when RETRIEVAL_BACKEND='azure'."""
    monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "false")
    monkeypatch.setenv("RETRIEVAL_BACKEND", "azure")

    with patch("app.main.generate_embedding", new_callable=AsyncMock) as mock_emb, \
         patch("app.db.azure_search.azure_hybrid_search", new_callable=AsyncMock) as mock_azure_search, \
         patch("app.main.chat_completion", new_callable=AsyncMock) as mock_llm:

        mock_emb.return_value = [0.1] * 1536
        mock_azure_search.return_value = [
            {
                "document_id": "azure-doc-1",
                "title": "Azure Architecture Reference",
                "content": "Azure search hybrid integration.",
                "chunk_index": 0,
                "allowed_roles": ["engineer"],
                "similarity": 0.96,
            }
        ]
        mock_llm.return_value = "Azure hybrid search is functional."

        response = client.post(
            "/api/v1/query",
            json={"question": "Tell me about Azure search."},
            headers={"X-User-Roles": '["engineer"]'},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["answer"] == "Azure hybrid search is functional."
        assert len(data["citations"]) == 1
        assert data["citations"][0]["document_id"] == "azure-doc-1"
        assert mock_azure_search.called
