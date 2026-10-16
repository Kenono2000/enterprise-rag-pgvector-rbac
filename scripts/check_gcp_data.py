"""
scripts/check_gcp_data.py
-------------------------
Verifies Google Cloud Vertex AI Vector Search live data:
1. Index Statistics & Vector Count via gcloud / Vertex AI Admin API
2. Live Vector Search Query (findNeighbors) with Zero-Trust RBAC Restricts
3. Hydrated Document Chunks & Confidence Metrics
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv, find_dotenv
load_dotenv(find_dotenv(), override=True)

import httpx
from app.db.gcp_search import get_gcp_config, get_gcp_access_token, gcp_hybrid_search
from app.db.llm import generate_embedding


async def check_index_metadata():
    print("=" * 65)
    print("1. Google Cloud Vertex AI Index & Endpoint Status")
    print("=" * 65)

    config = get_gcp_config()
    token = get_gcp_access_token()
    project_id = config["project_id"]
    region = config["region"]
    index_id = os.getenv("GCP_INDEX_ID", "4259655380562345984")
    endpoint_id = config["index_endpoint_id"]
    domain = config["public_domain"]

    print(f"Project ID:       {project_id}")
    print(f"Region:           {region}")
    print(f"Vector Index ID:  {index_id}")
    print(f"Endpoint ID:      {endpoint_id}")
    print(f"Public Domain:    {domain}")

    if not token:
        print("[WARN] Could not acquire Google OAuth2 access token.")
        return

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # Fetch Index Details & Vector Count
    index_url = f"https://{region}-aiplatform.googleapis.com/v1/projects/{project_id}/locations/{region}/indexes/{index_id}"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(index_url, headers=headers)
            if resp.status_code == 200:
                data = resp.json()
                stats = data.get("indexStats", {})
                print(f"\n[OK] Vertex AI Index Details:")
                print(f"  - Display Name:    {data.get('displayName')}")
                print(f"  - Update Method:   {data.get('indexUpdateMethod')}")
                print(f"  - Vectors Count:   {stats.get('vectorsCount', 'N/A')}")
                print(f"  - Shards Count:    {stats.get('shardsCount', 'N/A')}")
                print(f"  - Dimensions:      {data.get('metadata', {}).get('config', {}).get('dimensions', 1536)}")
                print(f"  - Distance Metric: {data.get('metadata', {}).get('config', {}).get('distanceMeasureType', 'COSINE_DISTANCE')}")
            else:
                print(f"[WARN] Index details status {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        print(f"[ERROR] Could not fetch index details: {exc}")


async def check_live_search():
    print("\n" + "=" * 65)
    print("2. Live Vector Search Query (findNeighbors + Restricts)")
    print("=" * 65)

    test_query = "what can ai do for me?"
    roles = ["finance_executive", "engineer"]

    print(f"Query:  \"{test_query}\"")
    print(f"Roles:  {roles}")
    print("\nGenerating 1536-d embedding and executing Zero-Trust search against GCP...")

    emb = await generate_embedding(test_query)
    results = await gcp_hybrid_search(test_query, emb, roles, limit=3)

    if not results:
        print("[FAIL] No results returned from Google Cloud Vertex AI Vector Search.")
        return

    print(f"\n[OK] Successfully retrieved {len(results)} authorized chunks from Vertex AI:\n")
    for idx, row in enumerate(results, 1):
        print(f"  [{idx}] {row.get('title', 'Document')}")
        print(f"      - Chunk ID:    {row.get('document_id', 'N/A')} (Chunk #{row.get('chunk_index', 0)})")
        print(f"      - Confidence:  {float(row.get('similarity', 0.0)):.4f}")
        print(f"      - RBAC Roles:  {row.get('allowed_roles', [])}")
        snippet = row.get('content', '').replace('\n', ' ')[:160]
        print(f"      - Content:     \"{snippet}...\"\n")


def check_cached_data():
    print("=" * 65)
    print("3. Local Metadata & JSONL Datapoints Summary")
    print("=" * 65)

    jsonl_path = PROJECT_ROOT / "scripts" / "gcp_datapoints.jsonl"
    cache_path = PROJECT_ROOT / "app" / "db" / "gcp_chunks_cache.json"

    if jsonl_path.exists():
        count = sum(1 for _ in open(jsonl_path, "r", encoding="utf-8"))
        size_kb = jsonl_path.stat().st_size / 1024
        print(f"  - scripts/gcp_datapoints.jsonl:  {count} vector records ({size_kb:.1f} KB)")
    else:
        print("  - scripts/gcp_datapoints.jsonl:  Not found")

    if cache_path.exists():
        with open(cache_path, "r", encoding="utf-8") as f:
            cache_data = json.load(f)
        size_kb = cache_path.stat().st_size / 1024
        print(f"  - app/db/gcp_chunks_cache.json:  {len(cache_data)} chunk records ({size_kb:.1f} KB)")
    else:
        print("  - app/db/gcp_chunks_cache.json:  Not found")
    print("=" * 65)


async def main():
    await check_index_metadata()
    await check_live_search()
    check_cached_data()


if __name__ == "__main__":
    asyncio.run(main())
