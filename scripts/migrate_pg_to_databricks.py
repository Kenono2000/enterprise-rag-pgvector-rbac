"""
scripts/migrate_pg_to_databricks.py
-----------------------------------
Extracts documents, chunks, and embeddings from PostgreSQL (pgvector)
and batch uploads or exports them to Databricks Mosaic AI Vector Search
and Unity Catalog Delta Table with Zero-Trust RBAC role filtering.
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
from app.db.databricks_search import get_databricks_config
import httpx


async def migrate_to_databricks(output_json: str = "scripts/databricks_chunks.json"):
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

    databricks_rows = []
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

        databricks_rows.append({
            "id": str(r["id"]),
            "document_id": str(r["document_id"]),
            "title": str(r["title"]),
            "content": str(r["content"]),
            "chunk_index": int(r["chunk_index"] or 0),
            "allowed_roles": roles,
            "embedding": embedding_vals,
        })

    # Save to local file for Databricks dbfs / volume upload or COPY INTO
    out_path = PROJECT_ROOT / output_json
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(databricks_rows, f, indent=2)
    print(f"[OK] Exported {len(databricks_rows)} records to {out_path}")

    # If Databricks endpoint and token are present, upsert directly via REST
    config = get_databricks_config()
    host = config["host"]
    token = config["token"]
    index_name = config["index_name"]

    if host and token:
        print(f"Attempting batch upsert to Databricks index '{index_name}'...")
        url = f"https://{host}/api/2.0/vector-search/indexes/{index_name}/upsert-data"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        # Format payload for Databricks Direct Access Vector Index
        columns = ["id", "document_id", "title", "content", "chunk_index", "allowed_roles", "embedding"]
        data_array = [
            [
                item["id"],
                item["document_id"],
                item["title"],
                item["content"],
                item["chunk_index"],
                item["allowed_roles"],
                item["embedding"],
            ]
            for item in databricks_rows[:100]
        ]
        payload = {
            "manifest": {"columns": [{"name": c} for c in columns]},
            "inputs": {"data_array": data_array},
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(url, json=payload, headers=headers)
                if resp.status_code == 200:
                    print(f"[OK] Successfully upserted {len(data_array)} rows into Databricks Vector Search!")
                else:
                    print(f"Databricks upsert returned {resp.status_code}: {resp.text}")
            except Exception as e:
                print(f"Databricks live upsert deferred: {e}")
    else:
        print("[NOTE] Direct Databricks upload skipped (configure DATABRICKS_HOST and DATABRICKS_TOKEN in .env).")


if __name__ == "__main__":
    asyncio.run(migrate_to_databricks())
