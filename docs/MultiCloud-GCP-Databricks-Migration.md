# Google Cloud & Databricks Multi-Cloud RAG Migration Plan & Execution Playbook

This consolidated playbook outlines the end-to-end plan, architectural mapping, cloud provisioning steps, data migration, and production validation for expanding the **Zero-Trust Enterprise RAG platform (`enterprise-rag-pgvector-rbac`)** to **Google Cloud (Vertex AI / BigQuery)** and **Databricks (Mosaic AI Vector Search / Unity Catalog)**.

---

## 1. Multi-Cloud Architecture & Component Mapping

| Platform Layer | PostgreSQL + Local Stack (`pgvector`) | Microsoft Azure AI Cloud (`azure`) | Google Cloud Platform (`gcp`) | Databricks Lakehouse (`databricks`) |
| :--- | :--- | :--- | :--- | :--- |
| **Vector Engine** | PostgreSQL 16 + `pgvector` (HNSW) | **Azure AI Search** (HNSW Profile) | **Vertex AI Vector Search** (ScaNN / Tree-AH) | **Databricks Mosaic AI Vector Search** (Direct Index) |
| **Lexical Engine** | PostgreSQL Full-Text (`tsvector`) | **Azure AI Search BM25** Engine | **BigQuery Text Search** / BM25 | **Databricks Full-Text Search** |
| **Re-Ranking** | Reciprocal Rank Fusion (RRF) | **Bing Semantic Ranker** | **Vertex AI Search Ranking API** | **Mosaic AI Cross-Encoder Ranker** |
| **Zero-Trust RBAC** | SQL `d.allowed_roles ?| $roles` | OData `allowed_roles/any(...)` | **Vertex Restricts** (`allowed_roles`) | **filters_json** (`allowed_roles`) + Unity Catalog |
| **Embeddings** | Public OpenAI `text-embedding-3-large` | Azure OpenAI `text-embedding-3-large` | **OpenAI / Azure** `text-embedding-3-large` (1536-d) | **Databricks Serving** `bge-large-en` |
| **Chat LLM** | Public OpenAI `gpt-4o` | Azure OpenAI `gpt-4o` | **Gemini 2.5 Flash / Pro** or **GPT-4o** | **Databricks DBRX / Llama 3.1 70B** |
| **Observability** | Jaeger All-In-One (Badger LSM) | Azure Application Insights | **Google Cloud Trace / Cloud Logging** | **Databricks MLflow System Tables** |

---

## 2. Phase-by-Phase Migration Plan

```mermaid
flowchart TD
    subgraph S1 ["1. Cloud Provisioning"]
        GCP_P["Phase 1A:<br/>Google Cloud Setup<br/>(Vertex AI Index)"]
        DBX_P["Phase 1B:<br/>Databricks Setup<br/>(Mosaic AI Index)"]
    end

    subgraph S2 ["2. Data Pipeline"]
        MIG["Phase 2:<br/>Batch Migration<br/>(PostgreSQL Chunks)"]
        VAL["Phase 3:<br/>Index Validation<br/>(RBAC Restricts)"]
    end

    subgraph S3 ["3. Routing & Cutover"]
        ENV["Phase 4:<br/>Switch Backend<br/>(gcp / databricks)"]
        TEST["Phase 5:<br/>Automated Testing<br/>(pytest & Invariants)"]
    end

    S1 --> S2
    S2 --> S3

    style S1 fill:#f8fafc,stroke:#94a3b8,stroke-width:1.5px
    style S2 fill:#f0f9ff,stroke:#0284c7,stroke-width:1.5px
    style S3 fill:#dcfce7,stroke:#22c55e,stroke-width:1.5px
```

---

## Phase 1: Cloud Resource Provisioning

### 1.1 Google Cloud (Vertex AI Vector Search)

1. **Create Index & Endpoint**:
   - In Google Cloud Console, navigate to **Vertex AI** → **Vector Search**.
   - Create an index with **1536 dimensions**, metric **COSINE**, and algorithm **Tree-AH (ScaNN)** with `STREAM_UPDATE`.
   - Deploy the index to an **Index Endpoint** with public endpoint enabled.
   - Configure restricts namespace: `allowed_roles` for Zero-Trust filtering.
2. **Production Provisioning Details**:
   - **GCP Project**: `gen-lang-client-0795078481` (Project Number `226714713434`, Region `us-central1`).
   - **Vector Index ID**: `4259655380562345984` (`enterprise-rag-index`).
   - **Index Endpoint ID**: `7285634525504208896` (`enterprise-rag-endpoint`).
   - **Deployed Index ID**: `enterprise_rag_index`.
   - **Public Data-Plane Domain**: `1876216656.us-central1-226714713434.vdb.vertexai.goog`.
3. **Deploying Index to Endpoint CLI**:
   ```bash
   gcloud ai index-endpoints deploy-index 7285634525504208896 \
       --deployed-index-id="enterprise_rag_index" \
       --display-name="enterprise_rag_index" \
       --index="4259655380562345984" \
       --project="gen-lang-client-0795078481" \
       --region="us-central1"
   ```
   > [!NOTE]
   > Index deployment on Vertex AI allocates dedicated serving nodes and typically takes **10–15 minutes** to propagate and bind public DNS.

4. **Critical REST API Findings & Architectural Guardrails**:
   - **Restricts Schema**: The REST API requires `"allowList"` (not `"allow"`) inside each restrict object under namespace `allowed_roles`.
   - **IndexDatapoint Schema**: `IndexDatapoint` only accepts `datapointId`, `featureVector`, `restricts`, and `crowdingTag`. Arbitrary text or metadata fields are rejected with `HTTP 400 Bad Request`.
   - **Data-Plane vs. Control-Plane**: The `:findNeighbors` query endpoint **must** be invoked against the public data-plane domain (`*.vdb.vertexai.goog`). Calling `:findNeighbors` on the regional control-plane (`*-aiplatform.googleapis.com`) results in `HTTP 501 UNIMPLEMENTED`.

### 1.2 Databricks (Mosaic AI Vector Search)

1. **Unity Catalog Delta Table**:
   - Create schema `main.enterprise_rag` and table `document_chunks`.
   - Enable Change Data Feed (`TBLPROPERTIES (delta.enableChangeDataFeed = true)`).
2. **Create Vector Search Endpoint**:
   - In Databricks Workspace, navigate to **Compute** → **Vector Search**.
   - Create endpoint `enterprise_vs_endpoint`.
   - Create index `main.enterprise_rag.document_chunks_index` with primary key `id`, embedding dimension `1536`, and metadata column `allowed_roles`.
3. **Declarative Validation**:
   ```powershell
   python scripts/setup_databricks_vector_search.py
   ```

---

## Phase 2: Environment Configuration

Update [`.env`](file:///c:/src/enterprise-rag-pgvector-rbac/.env) to configure Google Cloud or Databricks:

```ini
# ==============================================================================
# Backend Provider Switcher: 'pgvector', 'azure', 'gcp', 'databricks'
# ==============================================================================
RETRIEVAL_BACKEND="gcp"         # or "databricks", "azure", "pgvector"

# ==============================================================================
# Google Cloud Vertex AI Vector Search
# ==============================================================================
GCP_PROJECT_ID="gen-lang-client-0795078481"
GCP_REGION="us-central1"
GCP_INDEX_ENDPOINT_ID="7285634525504208896"
GCP_INDEX_ID="4259655380562345984"
GCP_DEPLOYED_INDEX_ID="enterprise_rag_index"
GCP_INDEX_ENDPOINT_DOMAIN="1876216656.us-central1-226714713434.vdb.vertexai.goog"
GCP_VECTOR_STORE="vertex_ai"
GEMINI_API_KEY="AQ.Ab8RN6..."

# ==============================================================================
# Databricks Mosaic AI Vector Search
# ==============================================================================
DATABRICKS_HOST="dbc-xxxx.cloud.databricks.com"
DATABRICKS_TOKEN="dapi_xxxxxxxxxxxxxxxx"
DATABRICKS_VECTOR_SEARCH_ENDPOINT_NAME="enterprise_vs_endpoint"
DATABRICKS_INDEX_NAME="main.enterprise_rag.document_chunks_index"
```

---

## Phase 3: Data Migration & Two-Tier Hydration

Run the specialized migration scripts or the unified migration orchestrator:

```powershell
# Option A: Migrate to Google Cloud Vertex AI (Upserts 69 vectors + builds local metadata cache)
python scripts/migrate_pg_to_gcp.py

# Option B: Migrate to Databricks Mosaic AI
python scripts/migrate_pg_to_databricks.py

# Option C: Unified multi-cloud execution across all platforms
python scripts/migrate_multicloud.py --target all
```

### Two-Tier Chunk Hydration Architecture
Because Vertex AI datapoints only store embeddings and namespace restricts:
1. **Tier 1 (Instant Local Cache)**: [`scripts/migrate_pg_to_gcp.py`](file:///c:/src/enterprise-rag-pgvector-rbac/scripts/migrate_pg_to_gcp.py) exports [`app/db/gcp_chunks_cache.json`](file:///c:/src/enterprise-rag-pgvector-rbac/app/db/gcp_chunks_cache.json), indexing all chunk UUIDs to full content, titles, and indices. [`app/db/gcp_search.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/db/gcp_search.py) hydrates nearest neighbors from this cache in **< 1ms**.
2. **Tier 2 (Database Fallback)**: For any new chunks not yet cached, [`app/db/gcp_search.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/db/gcp_search.py) queries PostgreSQL (`WHERE c.id::text = ANY($1::text[])`) using `DatabaseManager.get_pool()`.

---

## Phase 4: Zero-Trust Invariant Implementations

### Google Cloud Restricts ([`app/db/gcp_search.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/db/gcp_search.py))
```python
# Vertex AI Vector Search Restricts ensure unprivileged vectors are never traversed
restricts = [
    {
        "namespace": "allowed_roles",
        "allowList": sanitized_roles,
    }
]
results = await client.find_neighbors(
    query_vector=query_vector,
    restricts=restricts,
    limit=limit,
)
```

### Databricks Mosaic AI Filters ([`app/db/databricks_search.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/db/databricks_search.py))
```python
# In-engine Unity Catalog JSON filter
filters_dict = {"OR": [{"allowed_roles": role} for role in sanitized_roles]}
results = await client.query_index(
    query_vector=query_vector,
    filters_json=json.dumps(filters_dict),
    limit=limit,
)
```

> [!IMPORTANT]
> **Zero-Trust Rule**: If `user_roles` is empty or invalid, both `gcp_hybrid_search` and `databricks_hybrid_search` terminate immediately returning `[]` without contacting remote endpoints.

---

## Phase 5: Verification & Quality Assurance Runbook

```powershell
# 1. Run multi-cloud test suite
python -m pytest tests/test_multicloud_search.py -v

# 2. Run full platform regression test suite
python -m pytest -q
# Target: 100% green passing across all 110 tests (109 passed, 1 skipped)

# 3. Test interactive query in Streamlit
# Question: "what can ai do for me?" or "is AI useful to human being?"
# Expected: Returns 3 chunks from "AI Agents 2026_Mindstream-1.pdf" with synthesis and citations
```
