"""
app/db/protocols.py
-------------------
Defines structural subtyping protocols (PEP 544 / PEP 695 idioms) for vector search
backends (PostgreSQL pgvector, Azure AI Search, GCP Vertex AI, Databricks Mosaic AI).

Decouples storage engines from API endpoints and ensures zero-trust RBAC pre-filtering
contracts across all multi-cloud adapters.
"""
from __future__ import annotations

from typing import Protocol, List, Dict, Any, Optional, runtime_checkable


@runtime_checkable
class VectorSearchProvider(Protocol):
    """
    Protocol contract that every vector retrieval engine must implement.
    Guarantees strict Zero-Trust RBAC pre-filtering at the database/engine layer.
    """

    async def search(
        self,
        query_text: str,
        query_vector: List[float],
        user_roles: List[str],
        limit: int = 3,
        **kwargs: Any,
    ) -> List[Dict[str, Any]]:
        """
        Execute vector similarity search pre-filtered by authorized user roles.

        Args:
            query_text: The user's natural language question.
            query_vector: Dense embedding vector.
            user_roles: List of verified role claims for the calling principal.
            limit: Maximum document chunks to retrieve.
            **kwargs: Backend-specific tuning options (e.g. semantic configurations).

        Returns:
            List of matching chunks with document metadata and similarity scores.
            If user_roles is empty, MUST return an empty list immediately without
            executing engine queries.
        """
        ...
