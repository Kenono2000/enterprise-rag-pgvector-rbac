"""
tests/test_vector_protocols.py
------------------------------
Unit tests for app/db/protocols.py and app/db/adapters.py.
Validates structural subtyping compliance (runtime_checkable) and
zero-trust RBAC invariants across vector adapters.
"""
from __future__ import annotations

import pytest
from unittest.mock import patch, AsyncMock

from app.db.protocols import VectorSearchProvider
from app.db.adapters import (
    PgvectorSearchAdapter,
    AzureSearchAdapter,
    GCPSearchAdapter,
    DatabricksSearchAdapter,
    get_vector_search_adapter,
)


def test_adapters_satisfy_protocol():
    """Verify that all adapters structurally satisfy the VectorSearchProvider runtime protocol."""
    pg_adapter = PgvectorSearchAdapter()
    azure_adapter = AzureSearchAdapter()
    gcp_adapter = GCPSearchAdapter()
    databricks_adapter = DatabricksSearchAdapter()

    assert isinstance(pg_adapter, VectorSearchProvider)
    assert isinstance(azure_adapter, VectorSearchProvider)
    assert isinstance(gcp_adapter, VectorSearchProvider)
    assert isinstance(databricks_adapter, VectorSearchProvider)


def test_get_vector_search_adapter_factory():
    """Test the factory resolver for different providers and error on invalid provider."""
    assert isinstance(get_vector_search_adapter("pgvector"), PgvectorSearchAdapter)
    assert isinstance(get_vector_search_adapter("azure_ai_search"), AzureSearchAdapter)
    assert isinstance(get_vector_search_adapter("vertex_ai"), GCPSearchAdapter)
    assert isinstance(get_vector_search_adapter("databricks"), DatabricksSearchAdapter)

    with pytest.raises(ValueError, match="Unsupported vector search provider"):
        get_vector_search_adapter("unsupported_backend")


@pytest.mark.asyncio
async def test_all_adapters_enforce_zero_trust_empty_roles():
    """All adapters must instantly return empty results without downstream execution if user_roles is empty."""
    adapters = [
        PgvectorSearchAdapter(),
        AzureSearchAdapter(),
        GCPSearchAdapter(),
        DatabricksSearchAdapter(),
    ]
    for adapter in adapters:
        result = await adapter.search(
            query_text="Secret document",
            query_vector=[0.1] * 1536,
            user_roles=[],
            limit=5,
        )
        assert result == []


@pytest.mark.asyncio
async def test_pgvector_adapter_delegation():
    """Verify PgvectorSearchAdapter transforms and normalizes DatabaseManager results."""
    mock_rows = [
        {
            "id": 1,
            "document_id": "doc-1",
            "title": "Title 1",
            "content": "Content 1",
            "similarity": 0.89,
            "allowed_roles": ["engineer"],
        }
    ]
    with patch("app.db.adapters.DatabaseManager.secure_search", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_rows
        adapter = PgvectorSearchAdapter()
        res = await adapter.search("query", [0.1] * 1536, ["engineer"], limit=1)

        assert len(res) == 1
        assert res[0]["document_id"] == "doc-1"
        assert res[0]["similarity"] == 0.89
        mock_search.assert_awaited_once()
