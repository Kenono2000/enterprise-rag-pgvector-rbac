"""
app/db/adapters.py
------------------
Adapter implementations adhering to the VectorSearchProvider protocol.
Unifies PostgreSQL pgvector, Azure AI Search, Google Cloud Vertex AI,
and Databricks Mosaic AI search into consistent, pluggable adapters.
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional

from app.db.protocols import VectorSearchProvider
from app.db.manager import DatabaseManager
from app.db.azure_search import azure_hybrid_search
from app.db.gcp_search import gcp_hybrid_search
from app.db.databricks_search import databricks_hybrid_search


class PgvectorSearchAdapter:
    """PostgreSQL pgvector adapter with in-database GIN + HNSW iterative scanning."""

    async def search(
        self,
        query_text: str,
        query_vector: List[float],
        user_roles: List[str],
        limit: int = 3,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        if not user_roles:
            return []
        rows = await DatabaseManager.secure_search(
            query_vector=query_vector,
            user_roles=user_roles,
            limit=limit,
        )
        return [
            {
                "id": str(r.get("id")),
                "document_id": r.get("document_id"),
                "title": r.get("title"),
                "content": r.get("content"),
                "similarity": float(r.get("similarity", 0.0)),
                "allowed_roles": r.get("allowed_roles", []),
            }
            for r in rows
        ]


class AzureSearchAdapter:
    """Azure AI Search adapter with OData collection pre-filtering."""

    async def search(
        self,
        query_text: str,
        query_vector: List[float],
        user_roles: List[str],
        limit: int = 3,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        return await azure_hybrid_search(
            query_text=query_text,
            query_vector=query_vector,
            user_roles=user_roles,
            limit=limit,
        )


class GCPSearchAdapter:
    """Google Cloud Vertex AI Vector Search adapter with ScaNN namespace restricts."""

    async def search(
        self,
        query_text: str,
        query_vector: List[float],
        user_roles: List[str],
        limit: int = 3,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        return await gcp_hybrid_search(
            query_text=query_text,
            query_vector=query_vector,
            user_roles=user_roles,
            limit=limit,
        )


class DatabricksSearchAdapter:
    """Databricks Mosaic AI Vector Search adapter with Unity Catalog filters."""

    async def search(
        self,
        query_text: str,
        query_vector: List[float],
        user_roles: List[str],
        limit: int = 3,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        return await databricks_hybrid_search(
            query_text=query_text,
            query_vector=query_vector,
            user_roles=user_roles,
            limit=limit,
        )


def get_vector_search_adapter(provider_name: Optional[str] = None) -> VectorSearchProvider:
    """
    Factory function returning the configured VectorSearchProvider adapter.
    Defaults to 'pgvector'.
    """
    name = (provider_name or "pgvector").lower().strip()
    if name in ("pgvector", "postgres", "postgresql"):
        return PgvectorSearchAdapter()
    if name in ("azure", "azure_search", "azure_ai_search"):
        return AzureSearchAdapter()
    if name in ("gcp", "vertex", "vertex_ai"):
        return GCPSearchAdapter()
    if name in ("databricks", "mosaic", "mosaic_ai"):
        return DatabricksSearchAdapter()
    raise ValueError(f"Unsupported vector search provider: {provider_name}")
