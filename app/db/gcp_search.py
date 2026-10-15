"""
app/db/gcp_search.py
--------------------
Google Cloud Vertex AI Vector Search & BigQuery client implementation
with strict Zero-Trust RBAC restricts filtering.

Enforces in-engine pre-filtering via Vertex AI Vector Search Restricts
(namespace: allowed_roles, allowList: [user_roles]) or BigQuery row filtering.
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


def get_gcp_config() -> Dict[str, str]:
    """Retrieve Google Cloud configuration from environment variables."""
    load_dotenv(find_dotenv(), override=True)
    project_id = os.getenv("GCP_PROJECT_ID") or os.getenv("PROJECT_ID", "")
    project_number = os.getenv("GCP_PROJECT_NUMBER", "226714713434")
    region = os.getenv("GCP_REGION", "us-central1")
    index_endpoint_id = os.getenv("GCP_INDEX_ENDPOINT_ID", "")
    deployed_index_id = os.getenv("GCP_DEPLOYED_INDEX_ID", "enterprise_rag_index")
    public_domain = (
        os.getenv("GCP_INDEX_ENDPOINT_DOMAIN")
    )
    vector_store = os.getenv("GCP_VECTOR_STORE", "vertex_ai").lower()
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GCP_API_KEY", "")

    return {
        "project_id": project_id,
        "project_number": project_number,
        "region": region,
        "index_endpoint_id": index_endpoint_id,
        "deployed_index_id": deployed_index_id,
        "public_domain": public_domain,
        "vector_store": vector_store,
        "api_key": api_key,
    }


def get_gcp_access_token() -> Optional[str]:
    """Obtain a Google OAuth2 access token from service account credentials in .env or google-auth default."""
    try:
        from google.oauth2 import service_account
        from google.auth.transport.requests import Request

        client_email = os.getenv("CLIENT_EMAIL")
        private_key = os.getenv("PRIVATE_KEY")
        if client_email and private_key:
            pkey = private_key.replace("\\n", "\n")
            info = {
                "type": os.getenv("TYPE", "service_account"),
                "project_id": os.getenv("PROJECT_ID") or os.getenv("GCP_PROJECT_ID"),
                "private_key_id": os.getenv("PRIVATE_KEY_ID"),
                "private_key": pkey,
                "client_email": client_email,
                "client_id": os.getenv("CLIENT_ID"),
                "auth_uri": os.getenv("AUTH_URI", "https://accounts.google.com/o/oauth2/auth"),
                "token_uri": os.getenv("TOKEN_URI", "https://oauth2.googleapis.com/token"),
            }
            creds = service_account.Credentials.from_service_account_info(
                info,
                scopes=["https://www.googleapis.com/auth/cloud-platform"],
            )
            creds.refresh(Request())
            return creds.token
    except Exception as exc:
        logger.debug("Service account .env token acquisition note: %s", exc)

    try:
        import google.auth
        from google.auth.transport.requests import Request
        credentials, _ = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        credentials.refresh(Request())
        return credentials.token
    except Exception as exc:
        logger.debug("Could not retrieve GCP access token via ADC: %s", exc)
        return None


class GCPVectorSearchClient:
    """Async client wrapper for Google Cloud Vertex AI Vector Search."""

    def __init__(self, config: Optional[Dict[str, str]] = None):
        self.config = config or get_gcp_config()
        self.project_id = self.config["project_id"]
        self.region = self.config["region"]
        self.index_endpoint_id = self.config["index_endpoint_id"]
        self.deployed_index_id = self.config["deployed_index_id"]

    async def find_neighbors(
        self,
        query_vector: List[float],
        restricts: List[Dict[str, Any]],
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Query Vertex AI Vector Search Index Endpoint using the findNeighbors REST API.
        Applies restricts for in-engine Zero-Trust RBAC pre-filtering.
        """
        if not self.index_endpoint_id or not self.project_id:
            logger.warning("GCP Index Endpoint or Project ID not configured; returning empty list.")
            return []

        token = get_gcp_access_token()
        headers = {
            "Content-Type": "application/json",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        project_num = self.config.get("project_number", "226714713434")
        custom_domain = (
            self.config.get("public_domain")
            or os.getenv("GCP_INDEX_ENDPOINT_DOMAIN")
            or "1876216656.us-central1-226714713434.vdb.vertexai.goog"
        )
        primary_domain = custom_domain
        
        urls = [
            f"https://{primary_domain}/v1/projects/{project_num}/locations/{self.region}/indexEndpoints/{self.index_endpoint_id}:findNeighbors",
            f"https://1876216656.us-central1-226714713434.vdb.vertexai.goog/v1/projects/{project_num}/locations/{self.region}/indexEndpoints/{self.index_endpoint_id}:findNeighbors",
        ]

        payload = {
            "deployedIndexId": self.deployed_index_id,
            "queries": [
                {
                    "datapoint": {
                        "featureVector": query_vector,
                        "restricts": restricts,
                    },
                    "neighborCount": limit,
                }
            ],
        }

        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = None
            for target_url in urls:
                try:
                    resp = await client.post(target_url, json=payload, headers=headers)
                    if resp.status_code == 200:
                        break
                    else:
                        logger.debug("Attempted Vertex AI endpoint %s: status %s", target_url, resp.status_code)
                except Exception as exc:
                    logger.debug("Failed contacting %s: %s", target_url, exc)
                    continue

            if resp is None or resp.status_code != 200:
                err_msg = resp.text if resp is not None else "No response"
                code = resp.status_code if resp is not None else "N/A"
                logger.error("Vertex AI Vector Search error (%s): %s", code, err_msg)
                return []

            data = resp.json()
            neighbors = []
            nearest_neighbors = data.get("nearestNeighbors", [])
            if nearest_neighbors:
                for neighbor in nearest_neighbors[0].get("neighbors", []):
                    dp = neighbor.get("datapoint", {})
                    distance = neighbor.get("distance", 0.0)
                    # Convert distance to similarity score
                    similarity = 1.0 - float(distance) if distance <= 1.0 else 1.0 / (1.0 + float(distance))
                    
                    # Extract attributes stored in crowdingTag or numeric/string restricts
                    metadata = dp.get("metadata", {})
                    neighbors.append({
                        "id": dp.get("datapointId", ""),
                        "similarity": similarity,
                        "metadata": metadata,
                    })
            return neighbors


def get_gcp_vector_client() -> GCPVectorSearchClient:
    """Return an instance of GCPVectorSearchClient."""
    return GCPVectorSearchClient()


async def gcp_hybrid_search(
    query_text: str,
    query_vector: List[float],
    user_roles: List[str],
    limit: int = 3,
) -> List[Dict[str, Any]]:
    """
    Executes Zero-Trust Vector Search in Google Cloud Vertex AI Vector Search
    or BigQuery Vector Search with RBAC restricts pre-filtering.
    
    Zero-Trust Invariant: If user_roles is empty or invalid, terminates immediately
    returning [] without contacting the remote service.
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

    config = get_gcp_config()
    client = get_gcp_vector_client()

    # Build Vertex AI Restricts namespace clause:
    # Restricts guarantee the index traverses only points where allowed_roles overlaps sanitized_roles
    restricts = [
        {
            "namespace": "allowed_roles",
            "allowList": sanitized_roles,
        }
    ]

    try:
        raw_results = await client.find_neighbors(
            query_vector=query_vector,
            restricts=restricts,
            limit=limit,
        )
    except Exception as exc:
        logger.error("GCP Vector search invocation failed: %s", exc)
        return []

    ids = [str(item.get("id")) for item in raw_results if item.get("id")]
    hydrated_map: Dict[str, Dict[str, Any]] = {}
    if ids:
        try:
            from app.db.manager import DatabaseManager
            pool = await DatabaseManager.get_pool()
            async with pool.acquire() as conn:
                records = await conn.fetch(
                    """
                    SELECT c.id::text as id, d.document_id, d.title, c.content, c.chunk_index, d.allowed_roles
                    FROM document_chunks c
                    JOIN documents d ON c.document_id = d.id
                    WHERE c.id::text = ANY($1::text[])
                    """,
                    ids,
                )
                for r in records:
                    hydrated_map[str(r["id"])] = dict(r)
        except Exception as exc:
            logger.debug("Database chunk hydration deferred: %s", exc)

    matched_rows: List[Dict[str, Any]] = []
    for item in raw_results:
        c_id = str(item.get("id", ""))
        h = hydrated_map.get(c_id, {})
        meta = item.get("metadata", {})
        similarity = float(item.get("similarity", 0.0))
        matched_rows.append({
            "document_id": h.get("document_id") or meta.get("document_id", c_id),
            "title": h.get("title") or meta.get("title", f"GCP Document {c_id}"),
            "content": h.get("content") or meta.get("content", ""),
            "chunk_index": int(h.get("chunk_index", meta.get("chunk_index", 0)) or 0),
            "allowed_roles": h.get("allowed_roles") or meta.get("allowed_roles", sanitized_roles),
            "similarity": similarity,
            "similarity_score": similarity,
        })

    return matched_rows
