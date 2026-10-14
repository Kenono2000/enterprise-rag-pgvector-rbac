# Enterprise RAG & Multi-Cloud Architecture Master Playbook

Comprehensive operational guide, configuration reference, and architecture evolution roadmap for the **Zero-Trust Enterprise RAG (`enterprise-rag-pgvector-rbac`)** platform across **PostgreSQL + pgvector** and **Microsoft Azure AI**.

---

## 📑 Table of Contents
1. [Executive Summary & System Baseline](#1-executive-summary--system-baseline)
2. [Dual-Backend Architecture Matrix (PostgreSQL vs. Azure AI)](#2-dual-backend-architecture-matrix-postgresql-vs-azure-ai)
3. [Zero-to-One Azure AI Migration Guide](#3-zero-to-one-azure-ai-migration-guide)
   - [Phase 1: Azure Subscription & Portal Resource Setup](#phase-1-azure-subscription--portal-resource-setup)
   - [Phase 2: Environment Configuration & Dependencies](#phase-2-environment-configuration--dependencies)
   - [Phase 3: Index Provisioning with Vector Profiles & Semantic Ranker](#phase-3-index-provisioning-with-vector-profiles--semantic-ranker)
   - [Phase 4: Data & Vector Migration (PostgreSQL ➔ Azure AI Search)](#phase-4-data--vector-migration-postgresql--azure-ai-search)
   - [Phase 5: Dual-Mode Application Routing (FastAPI & Streamlit)](#phase-5-dual-mode-application-routing-fastapi--streamlit)
4. [Zero-Trust RBAC: In-Database vs. In-Engine OData Filtering](#4-zero-trust-rbac-in-database-vs-in-engine-odata-filtering)
5. [Telemetry & Observability: Jaeger Badger vs. Azure Application Insights](#5-telemetry--observability-jaeger-badger-vs-azure-application-insights)
6. [Solved Engineering Pitfalls & Azure Migration RCA](#6-solved-engineering-pitfalls--azure-migration-rca)
7. [Enterprise Verification & Quality Assurance Runbook](#7-enterprise-verification--quality-assurance-runbook)
8. [Multi-Cloud Evolution: GCP Vertex AI & Databricks Roadmap](#8-multi-cloud-evolution-gcp-vertex-ai--databricks-roadmap)

---

## 1. Executive Summary & System Baseline

### Repository Metadata
- **Repository Root**: `C:\src\enterprise-rag-pgvector-rbac`
- **Active Git Branch**: `feature/issues-15-16-17-hardening`
- **Core Technology Stack**: Python 3.11, PostgreSQL 16 (`pgvector`), Azure AI Search, Azure OpenAI (`gpt-4o`, `text-embedding-3-large`), FastAPI, Streamlit, FastMCP, OpenTelemetry.
- **Verification Baseline**: 99 offline tests (98 passed, 1 skipped) via `pytest`.

### Architectural Pillars
1. **Zero-Trust Retrieval**: Permissions are enforced strictly in the data engine prior to ranking. Documents outside a user's verified role claims never touch memory, cache, or LLM context.
2. **Dual-Mode Backend Resilience**: Seamless runtime switching between PostgreSQL (`RETRIEVAL_BACKEND="pgvector"`) and Microsoft Azure (`RETRIEVAL_BACKEND="azure"`).
3. **Cryptographic Session Security**: Google OAuth 2.0 PKCE with stateless HMAC tokens, encrypted browser session cookies, and 15-min idle / 12-hour maximum ceiling bounds.
4. **Full-Stack Observability**: Spans traverse Streamlit (`chat_interaction`), FastAPI REST endpoints (`http_request`), and MCP tool calls (`mcp_tool`), streaming into Jaeger Badger storage or Azure Application Insights.

---

## 2. Dual-Backend Architecture Matrix (PostgreSQL vs. Azure AI)

| Architecture Component | Primary: On-Premises / Open Source | Alternative: Microsoft Azure AI | Operational Benefit |
| :--- | :--- | :--- | :--- |
| **Vector Storage & Distance** | PostgreSQL 16 + `pgvector` (HNSW cosine ops) | **Azure AI Search** (HNSW Vector Profile) | Managed scaling, SLA-backed, zero DB maintenance. |
| **Lexical Keyword Search** | PostgreSQL Full-Text Search (`tsvector`, `ts_rank`) | **Azure AI Search BM25** Engine | Native inverted index optimized for document collections. |
| **Re-Ranking Engine** | Reciprocal Rank Fusion (RRF) + Heuristic / Cross-Encoder | **Bing Semantic Ranker** (`semantic-config`) | Deep transformer-based multi-lingual re-ranking. |
| **Access Control (RBAC)** | SQL Parameterized GIN filter: `WHERE allowed_roles ?| $user_roles` | **OData Collection Filter**: `allowed_roles/any(r: r eq '...')` | Zero memory leaks: unauthorized items pruned inside search engine. |
| **Embedding Generation** | OpenAI API `text-embedding-3-large` (1536-d) | **Azure OpenAI** `text-embedding-3-large` (3072-d / 1536-d) | Private VPC connectivity, no data used for AI training. |
| **Chat Generation (LLM)** | OpenAI API `gpt-4o` | **Azure OpenAI** `gpt-4o` (Deployments) | Private tenant hosting, enterprise compliance (SOC2/HIPAA). |
| **Distributed Tracing** | Jaeger All-In-One (Persistent Badger LSM-tree) | **Azure Application Insights** (Azure Monitor OTel) | Serverless telemetry dashboard with zero storage management. |

---

## 3. Zero-to-One Azure AI Migration Guide

### Phase 1: Azure Subscription & Portal Resource Setup

#### Step 1.1: Create a Dedicated Resource Group
1. Sign in to the [Azure Portal](https://portal.azure.com/).
2. Navigate to **Resource groups** ➔ Click **+ Create**.
3. Set **Resource group name**: `rg-enterprise-rag-dev` (or `rg-enterprise-rag-prod`).
4. Set **Region**: Select a region with model availability (e.g., `East US 2` or `Sweden Central`).
5. Click **Review + create** ➔ **Create**.

#### Step 1.2: Deploy Azure OpenAI Service & Models
1. Search for **Azure OpenAI** ➔ Click **+ Create**.
2. Select Resource Group `rg-enterprise-rag-dev`.
3. Provide a name: e.g., `oai-enterprise-rag`.
4. Pricing tier: **Standard S0** ➔ Click **Review + create** ➔ **Create**.
5. Once deployed, open the resource:
   - Navigate to **Keys and Endpoint** in the left sidebar.
   - Record **Endpoint** (`https://<name>.openai.azure.com/`) and **Key 1**.
6. Click **Go to Azure AI Foundry portal** (or Azure OpenAI Studio):
   - Under **Deployments**, click **+ Deploy model** ➔ **Deploy base model**.
   - Deploy `text-embedding-3-large` (Deployment name: `text-embedding-3-large`).
   - Click **+ Deploy model** ➔ Deploy `gpt-4o` (Deployment name: `gpt-4o`).

#### Step 1.3: Deploy Azure AI Search with Semantic Ranker
1. Search for **AI Search** ➔ Click **+ Create**.
2. Select Resource Group `rg-enterprise-rag-dev`.
3. Name: e.g., `search-enterprise-rag`.
4. Pricing tier: **Standard** (Standard is required for the Semantic Ranker).
5. Click **Review + create** ➔ **Create**.
6. When completed, open the resource:
   - In **Settings** ➔ **Keys**, copy the **URL** and **Primary admin key**.
   - In **Settings** ➔ **Semantic ranker**, enable the **Free** or Standard plan.

#### Step 1.4: Deploy Azure Application Insights
1. Search for **Application Insights** ➔ Click **+ Create**.
2. Select Resource Group `rg-enterprise-rag-dev`, Name: `appi-enterprise-rag`.
3. Click **Review + create** ➔ **Create**.
4. In the resource Overview blade, copy the **Connection String** (`InstrumentationKey=...`).

---

### Phase 2: Environment Configuration & Dependencies

Install required client packages:
```powershell
pip install azure-search-documents azure-identity azure-monitor-opentelemetry openai
```

Configure `.env` in Dual-Mode:
```ini
# ==============================================================================
# Backend Provider Switcher: 'pgvector' OR 'azure'
# ==============================================================================
RETRIEVAL_BACKEND="azure"

# ==============================================================================
# Azure OpenAI Configuration
# ==============================================================================
AZURE_OPENAI_ENDPOINT="https://oai-enterprise-rag.openai.azure.com/"
AZURE_OPENAI_API_KEY="<your-azure-openai-key-1>"
AZURE_OPENAI_API_VERSION="2024-06-01"
AZURE_OPENAI_CHAT_DEPLOYMENT="gpt-4o"
AZURE_OPENAI_EMBEDDING_DEPLOYMENT="text-embedding-3-large"

# ==============================================================================
# Azure AI Search Configuration
# ==============================================================================
AZURE_SEARCH_ENDPOINT="https://search-enterprise-rag.search.windows.net"
AZURE_SEARCH_API_KEY="<your-azure-search-primary-admin-key>"
AZURE_SEARCH_INDEX_NAME="enterprise-documents-index"

# ==============================================================================
# Azure Application Insights (Telemetry)
# ==============================================================================
APPLICATIONINSIGHTS_CONNECTION_STRING="InstrumentationKey=...;IngestionEndpoint=..."
```

---

### Phase 3: Index Provisioning with Vector Profiles & Semantic Ranker

The index schema is defined in [`scripts/setup_azure_search.py`](file:///C:/src/enterprise-rag-pgvector-rbac/scripts/setup_azure_search.py). It provisions:
- **HNSW Vector Profile**: 3072 dimensions matching `text-embedding-3-large`.
- **Bing Semantic Configuration**: Prioritized fields on `title` and `content`.
- **Multi-Role RBAC Field**: Collection of Strings (`allowed_roles`) configured as `filterable=True`.

Run index creation:
```powershell
python scripts/setup_azure_search.py
# Output: ✅ Successfully created / updated Azure AI Search index: enterprise-documents-index
```

---

### Phase 4: Data & Vector Migration (PostgreSQL ➔ Azure AI Search)

The data pipeline in [`scripts/migrate_pg_to_azure.py`](file:///C:/src/enterprise-rag-pgvector-rbac/scripts/migrate_pg_to_azure.py):
1. Connects to PostgreSQL via loop-aware `asyncpg`.
2. Queries normalized master `documents` joined to `document_chunks`.
3. Normalizes vector embeddings and JSONB role arrays into typed Azure Search documents.
4. Executes atomic batch upload via `SearchClient.upload_documents(...)`.

Run data migration:
```powershell
python scripts/migrate_pg_to_azure.py
# Output: ✅ Successfully uploaded documents to Azure AI Search!
```

---

### Phase 5: Dual-Mode Application Routing (FastAPI & Streamlit)

1. **FastAPI Dispatch ([`app/main.py`](file:///C:/src/enterprise-rag-pgvector-rbac/app/main.py))**:
   ```python
   if os.getenv("RETRIEVAL_BACKEND", "").lower() == "azure":
       from app.db.azure_search import azure_hybrid_search
       rows = await azure_hybrid_search(request.question, query_vector, user.roles, limit=3)
   else:
       rows = await DatabaseManager.hybrid_search(request.question, query_vector, user.roles)
   ```

2. **Streamlit UI ([`streamlit_app.py`](file:///C:/src/enterprise-rag-pgvector-rbac/streamlit_app.py))**:
   - Queries `azure_hybrid_search(...)` when configured.
   - Formats and displays executed OData query specifications in the **🔍 Executed RBAC Query** inspection panel.

---

## 4. Zero-Trust RBAC: In-Database vs. In-Engine OData Filtering

### PostgreSQL In-Database RBAC
```sql
SELECT d.document_id, d.title, c.chunk_index, c.content, d.allowed_roles, 
       1 - (c.embedding <=> $1::vector) AS similarity
FROM document_chunks c
JOIN documents d ON c.document_id = d.id
WHERE d.allowed_roles ?| $2::text[]
ORDER BY c.embedding <=> $1::vector
LIMIT $3;
```

### Azure AI Search OData RBAC
```python
role_clauses = " or ".join([f"r eq '{role}'" for role in sanitized_roles])
role_filter = f"allowed_roles/any(r: {role_clauses})"

results = await client.search(
    search_text=query_text,
    vector_queries=[vector_query],
    filter=role_filter,
    query_type="semantic",
    semantic_configuration_name="semantic-config",
    top=limit,
)
```

**Zero-Trust Guarantee**: In both implementations, if a user presents no verified roles (`user_roles = []`), the system terminates immediately and returns `[]` without querying the search engine.

---

## 5. Telemetry & Observability: Jaeger Badger vs. Azure Application Insights

In [`app/observability.py`](file:///C:/src/enterprise-rag-pgvector-rbac/app/observability.py), observability dynamically adapts to the deployment target:

1. **Azure Application Insights**: Configured automatically when `APPLICATIONINSIGHTS_CONNECTION_STRING` is detected using `azure.monitor.opentelemetry.configure_azure_monitor`.
2. **Jaeger Badger Exporter**: Uses standard OTLP gRPC (`http://localhost:4317`) pointing to the persistent Badger LSM-Tree container when running in local Docker or Kubernetes.

---

## 6. Solved Engineering Pitfalls & Azure Migration RCA

### RCA 1: Azure OpenAI Streaming `IndexError: list index out of range`
- **Symptom**: Streamlit threw `IndexError: list index out of range` at line 146 in `chat_completion_stream_sync`.
- **Root Cause**: Unlike public OpenAI which populates choices on all chunks, Azure OpenAI emits trailing chunks with empty `chunk.choices = []` containing moderation/filter annotations and prompt tokens. Unconditionally indexing `chunk.choices[0]` triggered an exception.
- **Resolution**: Added empty choices guards across all streaming generators in [`app/db/llm.py`](file:///C:/src/enterprise-rag-pgvector-rbac/app/db/llm.py):
  ```python
  for chunk in stream:
      if not chunk.choices:
          continue
      content = chunk.choices[0].delta.content or ""
  ```

### RCA 2: Windows IDE Pre-Tool Hook Node.js Crash
- **Symptom**: Automated tool calls failed with `Cannot find module ...\Ken Wong\...`.
- **Root Cause**: A pre-tool telemetry hook script failed to quote spaces in Windows user profile directories (`C:\Users\Ken Wong`).
- **Resolution**: Guarded against manual PowerShell string escapes (avoiding backtick `` `n `` artifacts) and verified offline test isolation.

### RCA 3: `python-dotenv` Syntax Warnings
- **Symptom**: `python-dotenv could not parse statement starting at line X`.
- **Root Cause**: Inline comment formatting and unquoted multi-line private keys in `.env`.
- **Resolution**: Cleaned `.env` key-value pairs with strict double quotes.

---

## 7. Enterprise Verification & Quality Assurance Runbook

### Running Azure Search Tests
```powershell
# Run Azure AI Search unit and RBAC tests
python -m pytest tests/test_azure_search.py -v
```

### Running Complete Regression Suite
```powershell
# Run all 99 automated unit, auth, schema, and vector tests
python -m pytest -q
# Target: 98 passed, 1 skipped
```

### Manual Verification Matrix
1. **Empty Roles**: Query with `X-User-Roles: []` ➔ Confirm immediate 0 results returned.
2. **Role Isolation**: Query as `engineer` ➔ Confirm Financial Audits are never returned.
3. **Bing Re-Ranking**: Inspect search results to verify `@search.reranker_score` is populated.

---

## 8. Multi-Cloud Evolution: GCP Vertex AI & Databricks Roadmap

For enterprise architectures spanning Google Cloud or Databricks:
- **Databricks Vector Search**: Sync Delta tables directly to managed HNSW indices.
- **Unity Catalog Row Filters**: Enforce `is_account_group_member(...)` for governance.
- **Google Cloud Vertex AI**: Deploy `gemini-1.5-pro` and `text-embedding-004` with Cloud Trace.
