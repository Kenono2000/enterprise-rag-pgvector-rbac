"""
scripts/migrate_pg_to_gcp.py
----------------------------
Extracts documents, chunks, and 1536-d embeddings from PostgreSQL (pgvector)
and batch uploads or exports them to Google Cloud Vertex AI Vector Search
(JSONL datapoints with Zero-Trust restricts) or BigQuery.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from dotenv import load_dotenv, find_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

load_dotenv(find_dotenv(), override=True)

from app.db import DatabaseManager
from app.db.gcp_search import get_gcp_config, get_gcp_access_token
import httpx


async def migrate_to_gcp(output_jsonl: str = "scripts/gcp_datapoints.jsonl"):
    print("Connecting to PostgreSQL to extract knowledge base chunks...")
    pool = await DatabaseManager.get_pool()

    sql = """
        SELECT c.id::text as id, d.document_id, d.title, c.content, c.chunk_index,
               d.allowed_roles, c.embedding
        FROM document_chunks c
        JOIN documents d ON c.document_id = d.id
    """

    async with pool.acquire() as conn:
        records = await conn.fetch(sql)
        print(f"Found {len(records)} chunk records in PostgreSQL.")

    if not records:
        print("No documents found in PostgreSQL to migrate.")
        return

    gcp_datapoints = []
    for r in records:
        raw_emb = r["embedding"]
        if isinstance(raw_emb, str):
            cleaned = raw_emb.strip("[]")
            embedding_vals = [float(x.strip()) for x in cleaned.split(",") if x.strip()]
        elif hasattr(raw_emb, "__iter__"):
            embedding_vals = [float(x) for x in raw_emb]
        else:
            embedding_vals = []

        raw_roles = r["allowed_roles"]
        if isinstance(raw_roles, list):
            roles = [str(x) for x in raw_roles]
        elif isinstance(raw_roles, str):
            try:
                roles = json.loads(raw_roles)
            except Exception:
                roles = [raw_roles]
        else:
            roles = []

        # Vertex AI Vector Search Datapoint format:
        # IndexDatapoints accept datapointId, featureVector, restricts (with allowList), and crowdingTag
        dp = {
            "datapointId": str(r["id"]),
            "featureVector": embedding_vals,
            "restricts": [
                {
                    "namespace": "allowed_roles",
                    "allowList": roles,
                }
            ],
            "crowdingTag": {
                "crowdingAttribute": str(r["document_id"]),
            },
        }
        gcp_datapoints.append(dp)

    # Write JSONL for Vertex AI batch index ingestion / GCS bucket upload / gcloud CLI
    out_path = PROJECT_ROOT / output_jsonl
    with open(out_path, "w", encoding="utf-8") as f:
        for dp in gcp_datapoints:
            f.write(json.dumps(dp) + "\n")
    print(f"[OK] Exported {len(gcp_datapoints)} Vertex AI datapoints to {out_path}")

    # If GCP index is reachable via API, upsert datapoints
    config = get_gcp_config()
    target_index_id = os.getenv("GCP_INDEX_ID") or config["index_endpoint_id"]
    token = get_gcp_access_token()
    if config["project_id"] and target_index_id and token:
        print(f"Uploading datapoints to Google Cloud Vertex AI Vector Search index {target_index_id}...")
        url = (
            f"https://{config['region']}-aiplatform.googleapis.com/v1/"
            f"projects/{config['project_id']}/locations/{config['region']}/"
            f"indexes/{target_index_id}:upsertDatapoints"
        )
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {"datapoints": gcp_datapoints}
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    print(f"[OK] Successfully upserted {len(gcp_datapoints)} datapoints into Vertex AI Vector Search!")
                else:
                    print(f"Vertex AI upsert status {resp.status_code}: {resp.text}")
            except Exception as e:
                print(f"Vertex AI upsert request deferred: {e}")
    else:
        print("[NOTE] Direct GCP upload skipped (configure GCP_INDEX_ID and credentials to enable live sync).")


if __name__ == "__main__":
    asyncio.run(migrate_to_gcp())
