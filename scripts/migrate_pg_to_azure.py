"""
scripts/migrate_pg_to_azure.py
------------------------------
Extracts documents and embeddings from PostgreSQL (pgvector)
and batch uploads them into Azure AI Search.
"""
from __future__ import annotations

import asyncio
import os
import sys
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(), override=True)

from app.db import DatabaseManager
from app.db.azure_search import get_search_client


async def migrate():
    print("Connecting to PostgreSQL...")
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
        print("No documents found to migrate.")
        return

    azure_docs = []
    for r in records:
        # Convert pgvector string/list into float list if needed
        raw_emb = r["embedding"]
        if isinstance(raw_emb, str):
            # Parse '[0.1, 0.2, ...]' format
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
            import json
            try:
                roles = json.loads(raw_roles)
            except Exception:
                roles = [raw_roles]
        else:
            roles = []

        azure_docs.append({
            "id": str(r["id"]),
            "document_id": str(r["document_id"]),
            "title": str(r["title"]),
            "content": str(r["content"]),
            "chunk_index": int(r["chunk_index"] or 0),
            "allowed_roles": roles,
            "embedding": embedding_vals,
        })

    client = get_search_client()
    async with client:
        print(f"Uploading {len(azure_docs)} documents to Azure AI Search...")
        result = await client.upload_documents(documents=azure_docs)
        print(f"✅ Successfully uploaded {len(result)} documents to Azure AI Search!")


if __name__ == "__main__":
    asyncio.run(migrate())
