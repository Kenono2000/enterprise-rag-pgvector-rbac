"""
app/db/databricks_search.py
---------------------------
Databricks Mosaic AI Vector Search client & hybrid retrieval implementation
with strict Zero-Trust RBAC filtering over Unity Catalog.

Enforces in-engine pre-filtering via Mosaic AI Vector Search filters_json
and Unity Catalog row-level constraints.
"""
from __future__ import annotations

import os
import json
import logging
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv, find_dotenv
import httpx

load_dotenv(find_dotenv(), override=True)

logger = logging.getLogger(__name__)


def get_databricks_config() -> Dict[str, str]:
    """Retrieve Databricks configuration from environment variables."""
    host = os.getenv("DATABRICKS_HOST", "").rstrip("/")
    if host.startswith("https://"):
        host = host[len("https://"):]
    elif host.startswith("http://"):
        host = host[len("http://"):]

    token = os.getenv("DATABRICKS_TOKEN", "")
    endpoint_name = os.getenv("DATABRICKS_VECTOR_SEARCH_ENDPOINT_NAME", "enterprise_vs_endpoint")
    index_name = os.getenv(
        "DATABRICKS_INDEX_NAME", "main.enterprise_rag.document_chunks_index"
    )

    return {
        "host": host,
        "token": token,
        "endpoint_name": endpoint_name,
        "index_name": index_name,
    }


class DatabricksVectorSearchClient:
    """Async client wrapper for Databricks Mosaic AI Vector Search REST API."""

    def __init__(self, config: Optional[Dict[str, str]] = None):
        self.config = config or get_databricks_config()
        self.host = self.config["host"]
        self.token = self.config["token"]
        self.index_name = self.config["index_name"]

    async def query_index(
        self,
        query_vector: List[float],
        query_text: Optional[str] = None,
        filters_json: Optional[str] = None,
        limit: int = 3,
        columns: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Query a Mosaic AI Vector Search index using /api/2.0/vector-search/indexes/{index_name}/query.
        """
        if not self.host or not self.token:
            logger.warning("Databricks Host or Token not configured; returning empty list.")
            return []

        if columns is None:
            columns = ["id", "document_id", "title", "content", "chunk_index", "allowed_roles"]

        url = f"https://{self.host}/api/2.0/vector-search/indexes/{self.index_name}/query"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        payload: Dict[str, Any] = {
            "num_results": limit,
            "columns": columns,
            "query_vector": query_vector,
        }
        if query_text:
            payload["query_text"] = query_text
        if filters_json:
            payload["filters_json"] = filters_json

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=payload, headers=headers)
            if resp.status_code != 200:
                logger.error("Databricks Vector Search error (%s): %s", resp.status_code, resp.text)
                return []

            data = resp.json()
            manifest = data.get("manifest", {})
            schema_cols = [c.get("name") for c in manifest.get("columns", [])]
            data_rows = data.get("result", {}).get("data_array", [])

            results: List[Dict[str, Any]] = []
            for row in data_rows:
                # Map row by column name
                row_dict = dict(zip(schema_cols, row)) if schema_cols else {}
                score = row[-1] if len(row) > len(schema_cols) else 1.0
                results.append({
                    "row": row_dict,
                    "score": float(score) if isinstance(score, (int, float)) else 1.0,
                })

            return results


def get_databricks_vector_client() -> DatabricksVectorSearchClient:
    """Return an instance of DatabricksVectorSearchClient."""
    return DatabricksVectorSearchClient()


async def databricks_hybrid_search(
    query_text: str,
    query_vector: List[float],
    user_roles: List[str],
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """
    Executes Zero-Trust Vector Search in Databricks Mosaic AI Vector Search
    with Unity Catalog RBAC pre-filtering.

    Zero-Trust Invariant: If user_roles is empty or invalid, terminates immediately
    returning [] without contacting Databricks.
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

    client = get_databricks_vector_client()

    # Build filters_json for Databricks Mosaic AI Vector Search.
    # Databricks supports JSON filter dicts matching column values.
    # For array containment or role matching:
    role_clauses = [{"allowed_roles": role} for role in sanitized_roles]
    if len(role_clauses) == 1:
        filters_dict = role_clauses[0]
    else:
        filters_dict = {"OR": role_clauses}
    filters_json = json.dumps(filters_dict)

    try:
        raw_results = await client.query_index(
            query_vector=query_vector,
            query_text=query_text,
            filters_json=filters_json,
            limit=limit,
        )
    except Exception as exc:
        logger.error("Databricks Vector Search invocation failed: %s", exc)
        return []

    matched_rows: List[Dict[str, Any]] = []
    for item in raw_results:
        row = item.get("row", {})
        score = float(item.get("score", 0.0))

        roles_val = row.get("allowed_roles", [])
        if isinstance(roles_val, str):
            try:
                roles_val = json.loads(roles_val)
            except Exception:
                roles_val = [roles_val]

        matched_rows.append({
            "document_id": str(row.get("document_id", row.get("id", ""))),
            "title": str(row.get("title", f"Databricks Document {row.get('id', '')}")),
            "content": str(row.get("content", "")),
            "chunk_index": int(row.get("chunk_index", 0) or 0),
            "allowed_roles": roles_val if isinstance(roles_val, list) else [str(roles_val)],
            "similarity": score,
            "similarity_score": score,
        })

    return matched_rows
