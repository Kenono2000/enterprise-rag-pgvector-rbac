"""
app/db/azure_search.py
----------------------
Azure AI Search client & hybrid search implementation with Zero-Trust RBAC filtering.
Enforces in-engine filtering via OData collection expressions (allowed_roles/any).
"""
from __future__ import annotations

import os
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(), override=True)

from azure.core.credentials import AzureKeyCredential
from azure.search.documents.aio import SearchClient
from azure.search.documents.models import VectorizedQuery


def get_search_client() -> SearchClient:
    """Return an asynchronous Azure AI Search client configured from environment variables."""
    endpoint = os.getenv("AZURE_SEARCH_ENDPOINT")
    index_name = os.getenv("AZURE_SEARCH_INDEX_NAME", "enterprise-documents-index")
    key = os.getenv("AZURE_SEARCH_API_KEY")

    if not endpoint or not key:
        raise ValueError("❌ AZURE_SEARCH_ENDPOINT and AZURE_SEARCH_API_KEY must be configured in environment.")

    return SearchClient(
        endpoint=endpoint,
        index_name=index_name,
        credential=AzureKeyCredential(key),
    )


async def azure_hybrid_search(
    query_text: str,
    query_vector: List[float],
    user_roles: List[str],
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """
    Executes Hybrid Search (Dense Vector + Keyword Search) with Bing Semantic Re-ranker
    in Azure AI Search, enforcing strict Zero-Trust RBAC filtering.
    
    If user_roles is empty, immediately returns empty results without querying.
    """
    if not user_roles:
        return []

    from app.auth.role_mapper import KNOWN_ROLES
    sanitized_roles = [
        str(r).strip() for r in user_roles
        if isinstance(r, str) and (str(r).strip() in KNOWN_ROLES or str(r).strip().isidentifier())
    ]
    if not sanitized_roles:
        return []

    client = get_search_client()
    async with client:
        # Build OData filter: allowed_roles contains ANY of user_roles
        # Example: allowed_roles/any(r: r eq 'engineer' or r eq 'executive')
        role_clauses = " or ".join([f"r eq '{role}'" for role in sanitized_roles])
        role_filter = f"allowed_roles/any(r: {role_clauses})"

        vector_query = VectorizedQuery(
            vector=query_vector,
            k_nearest_neighbors=limit,
            fields="embedding",
        )

        results = await client.search(
            search_text=query_text,
            vector_queries=[vector_query],
            filter=role_filter,
            query_type="semantic",
            semantic_configuration_name="semantic-config",
            top=limit,
        )

        matched_rows: List[Dict[str, Any]] = []
        async for item in results:
            # Semantic ranker score has priority, fall back to @search.score
            score = item.get("@search.reranker_score")
            if score is None:
                score = item.get("@search.score", 0.0)

            matched_rows.append({
                "document_id": item.get("document_id", item.get("id", "")),
                "title": item.get("title", ""),
                "content": item.get("content", ""),
                "chunk_index": item.get("chunk_index", 0),
                "allowed_roles": item.get("allowed_roles", []),
                "similarity": float(score),
                "similarity_score": float(score),
            })

        return matched_rows
