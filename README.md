# 🛡️ Enterprise Zero-Trust RAG & Autonomous SDLC

> **Architect:** **[Ken Wong](https://www.linkedin.com/in/kenwong-architect/)**  
> An enterprise-grade, shift-left reference implementation combining **In-Database Zero-Trust Vector RBAC** with an **Autonomous Self-Healing SDLC Agent**.  
> **Tech Stack:** PostgreSQL 16 + pgvector, FastAPI, Streamlit, Google OAuth 2.0 PKCE, Google JWKS, FastMCP, LangGraph.

---

## Live Interactive Artifacts

| Component | Description | Access Link |
| :--- | :--- | :--- |
| **Interactive UI** | Shift-Left In-Database RBAC & Session Monitor | [enterprise-rag-pgvector-rbac.streamlit.app](https://enterprise-rag-pgvector-rbac.streamlit.app) |
| **API Docs** | Live OpenAPI / Interactive Swagger UI | [enterprise-rag-api-ksez.onrender.com/docs](https://enterprise-rag-api-ksez.onrender.com/docs) |
| **Source Code** | Auditable Source Repository & Offline Test Suite | [github.com/Kenono2000/enterprise-rag-pgvector-rbac](https://github.com/Kenono2000/enterprise-rag-pgvector-rbac) |
| **Master Playbook** | Unified Architecture, STRIDE Matrix & Multi-Cloud Runbook | [Consolidated in `README.md`](#table-of-contents) |

---

## Table of Contents

1. [The Core Value: Why In-Database RBAC?](#the-core-value-why-in-database-rbac)
2. [System Architecture & Master Pipeline](#system-architecture--master-pipeline)
3. [Codebase Organization & Master File Cross-Reference](#codebase-organization--master-file-cross-reference)
4. [Architectural Deep Dive: The 8 Engineering Layers](#architectural-deep-dive-the-8-engineering-layers)
   - [Layer 1: Database & pgvector RBAC (schema.sql & app/db/)](#layer-1-database--pgvector-rbac-schemasql--appdb)
   - [Layer 2: Identity, Tokens & Session Security (app/auth/)](#layer-2-identity-tokens--session-security-appauth)
   - [Layer 3: High-Performance Ingestion Pipeline (scripts/ingest.py & libs/utilities.py)](#layer-3-high-performance-ingestion-pipeline-scriptsingestpy--libsutilitiespy)
   - [Layer 4: RAG Quality, Hybrid Search & Grounding Guardrails](#layer-4-rag-quality-hybrid-search--grounding-guardrails)
   - [Layer 5: FastAPI Backend & Streamlit Streaming Frontend](#layer-5-fastapi-backend--streamlit-streaming-frontend)
   - [Layer 6: Observability, Distributed Tracing & Container Hardening](#layer-6-observability-distributed-tracing--container-hardening)
   - [Layer 7: FastMCP Agent Gateway (app/mcp/)](#layer-7-fastmcp-agent-gateway-appmcp)
   - [Layer 8: Autonomous Self-Healing SDLC Agent (agent/)](#layer-8-autonomous-self-healing-sdlc-agent-agent)
5. [Threat Model & Security Architecture (STRIDE)](#threat-model--security-architecture-stride)
6. [5-Minute Quickstart](#5-minute-quickstart)
7. [Testing & Verification Guide (110 Tests: 109 Passed, 1 Skipped)](#testing--verification-guide-110-tests-109-passed-1-skipped)
8. [Solved Engineering Pitfalls & Root Cause Analysis](#solved-engineering-pitfalls--root-cause-analysis)
9. [Incident Response, Operational Runbook & Jaeger Persistence Verification](#incident-response-operational-runbook--jaeger-persistence-verification)
10. [Multi-Cloud Migration Playbook & Architecture (Azure, GCP, Databricks)](#multi-cloud-migration-playbook--architecture-azure-gcp-databricks)
11. [Disclaimer & Synthetic Data Security Notice](#disclaimer--synthetic-data-security-notice)

---

## The Core Value: Why In-Database RBAC?

Enterprise Generative AI deployments routinely suffer from critical vulnerabilities and degraded retrieval quality because authorization logic is implemented in the application layer *after* vector retrieval. Traditional enterprise RAG architectures filter permissions **after** vector retrieval in application memory, creating two catastrophic flaws:

```
❌ Standard Post-Filtering (Memory Leaks & Recall Starvation):
[Query] ──► [Vector DB: Top-K] ──► [Python App Filters by Role] ──► [LLM Context]
                                          │
                                          └─► Context Eviction & Memory Leaks

✅ Zero-Trust In-Database RBAC (Shift-Left Security):
[Query] ──► [Verified JWT] ──► [PostgreSQL: GIN Filter + HNSW Scan] ──► [LLM Context]
                                          │
                                          └─► Unauthorized data never leaves DB disk
```

1. **Eliminates Recall Starvation**: If top-$K$ documents belong to restricted tiers, post-filtering drops them all in Python memory—returning zero results even when authorized lower-ranked documents exist.
2. **Zero Memory Leaks**: In-database RBAC executes `WHERE allowed_roles ?| $user_roles` **before** vector distance calculation. Unauthorized documents are never read from disk into buffer cache, never sent over TLS, and never loaded into application RAM.

---

## System Architecture & Master Pipeline

### High-Level 4-Stage Architectural Flow

```mermaid
flowchart LR
    subgraph IdentityLayer ["1. Identity & Auth"]
        direction TB
        AuthCode["OAuth 2.0 PKCE<br/>(Google Cloud)"]
        JWKSValidator["JWKS Validator<br/>(RS256 Signature)"]
        RoleMapper["Role Extractor<br/>(Custom Claims)"]
        AuthCode --> JWKSValidator
        JWKSValidator --> RoleMapper
    end

    subgraph RetrievalLayer ["2. Data & Search"]
        direction TB
        PGVector["PostgreSQL 16<br/>(GIN + HNSW Index)"]
        CloudSearch["Cloud Vector Search<br/>(Azure / GCP / DBX)"]
        HybridRanker["Hybrid Ranker<br/>(RRF k=60 / BM25)"]
        PGVector --> HybridRanker
        CloudSearch --> HybridRanker
    end

    subgraph ServiceLayer ["3. Gateways & UI"]
        direction TB
        APIGateway["FastAPI Gateway<br/>(Async Stream SSE)"]
        MCPGateway["FastMCP Server<br/>(Tool Sandbox)"]
        StreamlitUI["Streamlit UI<br/>(Inspector Mode)"]
        APIGateway --> StreamlitUI
        MCPGateway --> StreamlitUI
    end

    subgraph SDLCLayer ["4. Self-Healing Agent"]
        direction TB
        AgentPropose["LangGraph Engine<br/>(State Machine)"]
        ASTGuardrail["AST Auditor<br/>(Banned Syscalls)"]
        PytestRunner["Pytest Harness<br/>(Automated TDD)"]
        AgentPropose --> ASTGuardrail
        ASTGuardrail --> PytestRunner
    end

    IdentityLayer --> RetrievalLayer
    RetrievalLayer --> ServiceLayer
    ServiceLayer --> SDLCLayer

    style IdentityLayer fill:#f8fafc,stroke:#94a3b8,stroke-width:1.5px
    style RetrievalLayer fill:#f0f9ff,stroke:#0284c7,stroke-width:1.5px
    style ServiceLayer fill:#fdf4ff,stroke:#c026d3,stroke-width:1.5px
    style SDLCLayer fill:#dcfce7,stroke:#22c55e,stroke-width:1.5px
```

### Detailed Multi-Cloud & Local System Topology

```mermaid
flowchart TB
    subgraph Clients ["Client & Consumer Layer"]
        browser["Streamlit UI / Web Client<br/>(localhost:8501)"]
        mcp_client["AI Agent / Cursor / Claude Desktop"]
    end

    subgraph Security ["Identity & Session Security (PKCE)"]
        google["Google OAuth 2.0 PKCE<br/>(accounts.google.com)"]
        jwks["Google JWKS (RS256)<br/>leeway=60s"]
        cookie["Encrypted Session Cookie<br/>(15m idle / 12h ceiling)"]
    end

    subgraph PythonEnv ["🐍 Python Local / Container Environment (RETRIEVAL_BACKEND='pgvector')"]
        api["FastAPI Gateway (:8000)<br/>POST /api/v1/query"]
        mcp_gw["FastMCP Server<br/>Tool: search_sdlc_context"]
        pool["Loop-Aware asyncpg Pool"]
        local_db["PostgreSQL 16 + pgvector (:5432)<br/>• GIN: allowed_roles jsonb_path_ops<br/>• HNSW: embedding vector_cosine_ops"]
        openai_api["OpenAI API (Public Endpoint)<br/>• text-embedding-3-large (1536-d)<br/>• gpt-4o Chat Completions"]
        jaeger["Jaeger All-In-One (:16686)<br/>Persistent Badger LSM Storage"]
    end

    subgraph MultiCloudEnv ["☁️ Multi-Cloud Managed Enterprise Environments"]
        direction TB
        subgraph AzureEnv ["Microsoft Azure (RETRIEVAL_BACKEND='azure')"]
            azure_search["Azure AI Search<br/>• allowed_roles/any(...)<br/>• Bing Semantic Ranker"]
            azure_oai["Azure OpenAI Service<br/>• text-embedding-3-large<br/>• gpt-4o Deployments"]
            app_insights["Azure Application Insights<br/>Managed OpenTelemetry Dashboard"]
        end
        subgraph GcpEnv ["Google Cloud (RETRIEVAL_BACKEND='gcp')"]
            gcp_search["Vertex AI Vector Search<br/>• Restricts: allowed_roles<br/>• ScaNN 1536-d Index"]
            gcp_gemini["Vertex AI / Gemini API<br/>• text-embedding-004<br/>• Gemini 1.5 Pro / Flash"]
        end
        subgraph DbxEnv ["Databricks (RETRIEVAL_BACKEND='databricks')"]
            dbx_search["Mosaic AI Vector Search<br/>• Unity Catalog RBAC<br/>• Delta Lake Direct Index"]
            dbx_serving["Databricks Model Serving<br/>• bge-large-en<br/>• DBRX / Llama 3.1 70B"]
        end
    end

    subgraph AgentEngine ["🤖 Autonomous SDLC Agent (agent/)"]
        langgraph["LangGraph State Machine<br/>propose ➔ apply ➔ audit ➔ test ➔ repair"]
        guardrails["PolicyEngine<br/>Deterministic AST + Secret Scanner"]
    end

    %% Auth Flow
    browser -->|1. PKCE Auth Code| google
    google -->|2. RS256 ID Token| browser
    browser -->|3. Encrypted Cookie / Bearer| cookie
    browser -->|4. Authenticated Request| api
    api -->|5. Verify Token & Leeway| jwks

    %% In-process Gateways & Agent Coordination
    mcp_client -->|Governed Tool Call| mcp_gw
    AgentEngine -->|Context Hydration| api

    %% Python Env Routing
    api -.->|RETRIEVAL_BACKEND='pgvector'| pool
    mcp_gw -.->|RETRIEVAL_BACKEND='pgvector'| pool
    pool -->|GIN Filter + Cosine Distance| local_db
    local_db -->|Authorized Top-K| api
    api -.->|Generate Vectors / Chat| openai_api
    api -.->|OTel Tracing| jaeger

    %% Multi-Cloud Routing
    api ==>|RETRIEVAL_BACKEND='azure'| azure_search
    mcp_gw ==>|RETRIEVAL_BACKEND='azure'| azure_search
    azure_search ==>|OData Filtered + Semantic Top-K| api
    api ==>|Private VPC Inference| azure_oai
    api ==>|Azure Monitor Telemetry| app_insights

    api ==>|RETRIEVAL_BACKEND='gcp'| gcp_search
    mcp_gw ==>|RETRIEVAL_BACKEND='gcp'| gcp_search
    gcp_search ==>|Restricts Filtered Top-K| api
    api ==>|Gemini Model APIs| gcp_gemini

    api ==>|RETRIEVAL_BACKEND='databricks'| dbx_search
    mcp_gw ==>|RETRIEVAL_BACKEND='databricks'| dbx_search
    dbx_search ==>|UC Filtered Top-K| api
    api ==>|Serving Endpoint LLM| dbx_serving

    %% User Response
    api -->|Grounded Answer + Citations| browser

    %% Visual Styling
    style PythonEnv fill:#f0f9ff,stroke:#0284c7,stroke-width:2px,stroke-dasharray: 4 4
    style MultiCloudEnv fill:#fdf4ff,stroke:#c026d3,stroke-width:2px
    style AzureEnv fill:#ffffff,stroke:#9333ea,stroke-width:1.5px
    style GcpEnv fill:#ffffff,stroke:#ea4335,stroke-width:1.5px
    style DbxEnv fill:#ffffff,stroke:#ff3621,stroke-width:1.5px
    style Security fill:#f0fdf4,stroke:#16a34a,stroke-width:2px
    style Clients fill:#fefce8,stroke:#ca8a04,stroke-width:2px
    style AgentEngine fill:#fffbeb,stroke:#d97706,stroke-width:2px
    style local_db fill:#e0f2fe,stroke:#0369a1,stroke-width:2px
    style azure_search fill:#fae8ff,stroke:#a21caf,stroke-width:2px
    style gcp_search fill:#fee2e2,stroke:#b91c1c,stroke-width:2px
    style dbx_search fill:#ffedd5,stroke:#c2410c,stroke-width:2px
```

---

## Codebase Organization & Master File Cross-Reference

```text
enterprise-rag-pgvector-rbac/
├── app/                        # 🛡️ Zero-Trust RAG Microservice
│   ├── auth/                   # Identity: PKCE, JWKS verification, session cookies, role mapping
│   ├── db/                     # Data & AI: asyncpg pooling, pgvector, Azure AI Search, GCP Vertex AI, Databricks
│   │   ├── azure_search.py     # Azure AI Search client with OData collection RBAC filtering
│   │   ├── gcp_search.py       # Google Cloud Vertex AI Vector Search client with RBAC restricts
│   │   ├── databricks_search.py# Databricks Mosaic AI Vector Search client with Unity Catalog filters
│   │   ├── llm.py              # Multi-model LLM abstraction (Azure OpenAI, Gemini, Databricks, OpenAI)
│   │   └── manager.py          # PostgreSQL asyncpg pool manager & hybrid search
│   ├── mcp/                    # FastMCP tools & policy resources for external AI agents
│   ├── observability.py        # Observability metrics, Azure Application Insights & OTel tracing
│   ├── config.py               # Pydantic BaseSettings environment validation
│   └── main.py                 # FastAPI REST API (/api/v1/query, /healthz, /readyz, /webhooks/github)
│
├── agent/                      # 🤖 Autonomous Self-Healing SDLC Agent
│   ├── workflow.py             # LangGraph state machine (patch -> audit -> test -> repair -> PR)
│   ├── guardrails.py           # Deterministic AST inspection & secret scanners
│   └── parser.py               # GitHub webhook event parser & HMAC signature verifier
│
├── libs/                       # 📚 Shared Utilities & Algorithms
│   └── utilities.py            # Tiktoken chunk splitting, SHA-256 de-dup, RRF fusion, Cross-Encoder
│
├── scripts/                    # ⚙️ Operational & Ingestion Scripts
│   ├── ingest.py               # Enterprise multi-format batch ingestion with SHA-256 change detection
│   ├── setup_azure_search.py   # Azure AI Search index provisioning with HNSW & semantic config
│   ├── migrate_pg_to_azure.py  # Batch migration pipeline copying documents & vectors from PG to Azure Search
│   ├── setup_gcp_vector_search.py # Google Cloud Vertex AI / BigQuery Vector Search setup
│   ├── migrate_pg_to_gcp.py    # Batch migration pipeline copying documents & vectors from PG to Vertex AI
│   ├── setup_databricks_vector_search.py # Databricks Unity Catalog & Mosaic AI Vector Search setup
│   ├── migrate_pg_to_databricks.py # Batch migration pipeline copying documents & vectors to Databricks
│   └── migrate_multicloud.py   # Unified multi-cloud migration orchestrator (--target azure|gcp|databricks|all)
│
├── tests/                      # 🧪 Automated Test Suite (110 Tests: 109 Passed, 1 Skipped)
│   ├── test_auth.py            # PKCE cryptography, JWKS leeway, session cookie tests
│   ├── test_azure_search.py    # Azure AI Search hybrid search, OData RBAC filters, dual-backend routing
│   ├── test_multicloud_search.py # Google Cloud Vertex AI & Databricks Mosaic AI search & routing
│   ├── test_database_schema.py # Normalized DDL, indexes, cascading deletes, benchmark simulation
│   ├── test_hybrid_search.py   # RRF math, candidate re-ranking, GroundingGuardrail validation
│   ├── test_ingest.py          # SHA-256 de-duplication, stem matching, modified file re-indexing
│   ├── test_integration_pgvector.py # Testcontainers pgvector/pg16 integration harness
│   ├── test_mcp_auth.py        # FastMCP authentication & tool access governance
│   ├── test_observability_and_health.py # Probes (/healthz, /readyz), BaseSettings, token streaming
│   ├── test_rag.py             # RAG endpoints & in-database RBAC tests
│   ├── test_security_rbac.py   # SQL injection immunity, parameterized array bindings ($2::text[])
│   ├── test_utilities.py       # Multi-format loaders, chunk metadata, tenacity retry
│   └── test_agent.py           # LangGraph workflow, AST guardrails, path traversal tests
│
├── streamlit_app.py            # 🖥️ Interactive Web UI (PKCE auth, cookie session persistence, live RAG)
├── schema.sql                  # PostgreSQL schema, HNSW/GIN indexes, seed mock data
├── Dockerfile                  # Multi-stage non-root hardened container definition
└── requirements.txt            # Production dependencies
```

### Master File & Symbol Cross-Reference

| System Layer | File Location | Key Symbols & Responsibilities |
| :--- | :--- | :--- |
| **Database Schema** | [`schema.sql`](file:///c:/src/enterprise-rag-pgvector-rbac/schema.sql) | DDL tables `documents`, `document_chunks`, HNSW/GIN indexes. |
| **PostgreSQL Client** | [`app/db/manager.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/db/manager.py) | `DatabaseManager`, `hybrid_search`, `secure_search`, `asyncpg` connection pool. |
| **Azure Search** | [`app/db/azure_search.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/db/azure_search.py) | `azure_hybrid_search`, OData collection role filtering (`allowed_roles/any(...)`). |
| **GCP Vertex AI Search** | [`app/db/gcp_search.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/db/gcp_search.py) | `gcp_hybrid_search`, Vertex AI Vector Search `restricts` pre-filtering & two-tier cache hydration. |
| **Databricks Search** | [`app/db/databricks_search.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/db/databricks_search.py) | `databricks_hybrid_search`, Mosaic AI Vector Search Unity Catalog `filters_json` RBAC. |
| **Multi-Model LLM** | [`app/db/llm.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/db/llm.py) | `get_openai_client`, `chat_completion_stream`, multi-cloud model abstraction & guardrails. |
| **Identity & PKCE** | [`app/auth/pkce.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/auth/pkce.py) | `generate_pkce_pair`, `encode_pkce_state`, `decode_pkce_state`, encrypted session cookie helpers. |
| **JWKS Security** | [`app/auth/jwks.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/auth/jwks.py) | `verify_jwt_token`, `get_allowed_issuers`, TTL public key cache manager (`leeway=60s`). |
| **Role Extraction** | [`app/auth/role_mapper.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/auth/role_mapper.py) | `resolve_user_roles`, `KNOWN_ROLES` entitlement validator & multi-IdP claim normalization. |
| **FastAPI Gateway** | [`app/main.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/main.py) | FastAPI lifecycle, dependency injection, `/api/v1/query`, `/healthz`, `/readyz`, `/webhooks/github`. |
| **FastMCP Server** | [`app/mcp/gateway.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/mcp/gateway.py) | `search_sdlc_context`, `propose_patch` MCP tools & `policy://sdlc-budget` resource. |
| **Observability** | [`app/observability.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/observability.py) | OpenTelemetry tracer provider, Jaeger Badger LSM-tree & Azure Monitor exporters. |
| **SDLC State Machine**| [`agent/workflow.py`](file:///c:/src/enterprise-rag-pgvector-rbac/agent/workflow.py) | LangGraph autonomous SDLC graph (`propose` ➔ `apply` ➔ `audit` ➔ `test` ➔ `repair` ➔ `PR`). |
| **AST Guardrails** | [`agent/guardrails.py`](file:///c:/src/enterprise-rag-pgvector-rbac/agent/guardrails.py) | `PolicyEngine`, `GroundingGuardrail`, AST static code inspection & secret scanner. |

---

## Architectural Deep Dive: The 8 Engineering Layers

### Layer 1: Database & pgvector RBAC (schema.sql & app/db/)

#### Normalized Schema & Dual-Index Strategy (`schema.sql`)
The schema cleanly decouples master document records from vector embeddings using a foreign key with `ON DELETE CASCADE`. This eliminates duplicate metadata storage and simplifies document lifecycle management:

```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Master Documents Table
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id VARCHAR(100) NOT NULL UNIQUE,
    title VARCHAR(255) NOT NULL,
    source_path TEXT,
    file_hash CHAR(64) UNIQUE,
    file_type VARCHAR(16) DEFAULT 'markdown',
    allowed_roles JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 2. Document Chunks Table with Foreign Key & Cascade Deletion
CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_id VARCHAR(128) NOT NULL UNIQUE,
    chunk_index INT NOT NULL DEFAULT 0,
    content TEXT NOT NULL,
    token_count INT,
    embedding vector(1536) NOT NULL,
    embedding_model VARCHAR(100) DEFAULT 'text-embedding-3-large',
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 3. HNSW Vector Index: sub-millisecond approximate nearest neighbor search
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw 
ON document_chunks USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- 4. GIN Role Index: constant-time JSONB role membership pre-filter
CREATE INDEX IF NOT EXISTS idx_documents_allowed_roles_gin 
ON documents USING gin (allowed_roles jsonb_path_ops);

-- 5. B-Tree Hash Index: instant cryptographic de-duplication
CREATE INDEX IF NOT EXISTS idx_documents_file_hash 
ON documents (file_hash);

-- 6. GIN Full-Text Search Index: sparse keyword matching & lexical rank
CREATE INDEX IF NOT EXISTS idx_chunks_content_tsv 
ON document_chunks USING gin (tsv);
```

#### The Core In-Database RBAC Query (`app/db/manager.py`)
```sql
SELECT d.document_id, d.title, c.chunk_index, c.content, d.allowed_roles, 
       1 - (c.embedding <=> $1::vector) AS similarity
FROM document_chunks c
JOIN documents d ON c.document_id = d.id
WHERE d.allowed_roles ?| $2::text[]
  AND (c.embedding_model = 'text-embedding-3-large' OR c.embedding_model IS NULL)
ORDER BY c.embedding <=> $1::vector
LIMIT $3;
```

* **`?|` (JSONB Exists-Any)**: Evaluates whether any user role matches any element in `documents.allowed_roles`. The GIN index evaluates this condition before calculating vector distances.
* **`<=>` (Cosine Distance)**: Calculates distance $1 - \cos(\theta)$. Subtracting from 1 normalizes the value into a similarity score in $[0.0, 1.0]$.

#### Key Database Invariants & Optimizations
1. **Parameterized Query Execution & SQL Injection Immunity**: All vector searches execute exclusively via parameterized array containment (`WHERE allowed_roles ?| $2::text[]`). String interpolation into `ARRAY[...]` is strictly banned.
2. **Zero-Trust Short-Circuiting**: In `DatabaseManager.secure_search`, if `user_roles` is empty or `None`, the function returns `[]` immediately without executing a query against PostgreSQL.
3. **Defense-in-Depth Sanitization**: Vector search roles are sanitized against `KNOWN_ROLES` and identifier syntax, dropping SQL injection strings before binding to `$2::text[]`.
4. **Matryoshka 1536-d Truncation**: Truncates `text-embedding-3-large` from 3072 to 1536 dimensions, slashing PostgreSQL disk and RAM usage by **50%** while preserving **>98%** retrieval recall.
5. **Loop-Aware Connection Pooling**: `asyncpg` pools are bound to the running event loop. Streamlit recycles event loops across interactions; `DatabaseManager.get_pool()` detects closed/mismatched loops and recycles the pool automatically to prevent `RuntimeError: Event loop is closed`.
6. **Deterministic Mock Vectors (Offline Testing)**:
   * **Python**: `[0.01 * (i % 5) for i in range(1536)]`
   * **SQL**: `(SELECT array_agg(0.01 * (i % 5))::vector(1536) FROM generate_series(1, 1536) i)`
   * Enables comprehensive unit testing with zero external API calls, latency, or token costs.

---

### Layer 2: Identity, Tokens & Session Security (app/auth/)

#### 1. RFC 7636 OAuth 2.0 PKCE Flow
PKCE protects authorization codes from interception in public web and single-page applications:

```mermaid
sequenceDiagram
    autonumber
    actor Browser as User Browser / Streamlit
    participant Google as accounts.google.com
    participant App as App Server (app/auth/)
    participant JWKS as Google Public JWKS

    Browser->>Browser: Generate code_verifier (64 URL-safe bytes) & code_challenge (S256)
    Browser->>Browser: Mint HMAC-SHA256 signed state (stateless, zero-storage)
    Browser->>Google: Redirect to /auth with code_challenge & state
    Google->>Browser: User consents -> Redirect with ?code=XXX&state=YYY
    Browser->>App: Validate state signature & exchange code + verifier at /token
    Google-->>App: Returns {id_token, access_token, refresh_token}
    App->>JWKS: Fetch Google public certs (RS256) -> verify with leeway=60s
    App->>Browser: Set encrypted session cookie & render RAG workspace
```

#### 2. Stateless HMAC-Signed OAuth State
To avoid server-side session dependencies during OAuth redirects:
* `encode_pkce_state(verifier)` embeds the verifier and timestamp into an HMAC-SHA256 signed token: `"{b64_payload}.{sig}"`.
* On return, `decode_pkce_state()` verifies the signature in constant time and checks a 5-minute TTL.
* **Benefit**: Survives server restarts, multi-worker scale-outs, and browser navigations without a database or Redis.

#### 3. Token Architecture: The Three-Tier Security Model
| Token Type | Purpose | Lifetime | Storage Location |
| :--- | :--- | :--- | :--- |
| **ID Token (OIDC)** | User identity & verified `app_roles` | 15–60 min | In-memory session state |
| **Access Token (OAuth)** | Scoped API authorization | 15–60 min | Ephemeral memory |
| **Refresh Token (OAuth)** | Silent re-minting without re-entering credentials | 30 days | HttpOnly encrypted cookie / server store |

#### 4. Encrypted Cookie Session Persistence & Browser Reloads (F5)
* **The Problem**: Streamlit maintains `st.session_state` in ephemeral server memory tied to the active WebSocket. Pressing F5 severs the WebSocket, clearing `st.session_state` and forcing a re-login.
* **The Solution (`app/auth/pkce.py` & `streamlit_app.py`)**:
  1. On login, the app compresses (`zlib`), base64url-encodes, and HMAC-signs session data into an `enterprise_rag_session` cookie.
  2. A DOM tracker writes this to `parent.document.cookie`.
  3. On page refresh (F5), `_restore_session_from_cookie()` reads `st.context.cookies`, validates the HMAC signature, and rehydrates `st.session_state`.
  4. If the ID token is nearing expiration, it triggers a silent token refresh via `_refresh_id_token_sync()` automatically.

#### 5. Session Expiration & Termination Rules (SOC-2 / HIPAA)
```mermaid
flowchart LR
    Check["Session Event<br/>(Periodic Check)"] --> Idle{"Inactivity<br/>> 15 min?"}
    Idle -->|Yes| Terminate["Terminate Session<br/>(Wipe Cookie & Login)"]
    Idle -->|No| Ceiling{"Total Session<br/>> 12 hours?"}
    Ceiling -->|Yes| Terminate
    Ceiling -->|No| Refresh["Silent Token Refresh<br/>(via Google /token)"]
    Refresh --> OK["Session Active<br/>& Protected"]

    style Terminate fill:#fee2e2,stroke:#ef4444,stroke-width:1.5px
    style OK fill:#dcfce7,stroke:#22c55e,stroke-width:1.5px
    style Check fill:#f3e8ff,stroke:#a855f7,stroke-width:1.5px
```

1. **15-Minute Sliding Inactivity Timeout**: DOM event listeners track user activity (`mousedown`, `keydown`, `scroll`, `touchstart`). If 15 minutes elapse without interaction, the cookie is wiped (`max-age=0`) and the user is redirected to the sign-in page with a SOC-2 notice.
2. **12-Hour Hard Session Ceiling**: Regardless of continuous user activity, sessions terminate after 12 hours to require re-authentication.
3. **Role Resolution Pipeline**:
   * **Primary (Verified Token Claims)**: Extracts and normalizes claims from `app_roles`, `roles`, `groups`, `cognito:groups`, and `realm_access.roles` (supporting Azure AD, Okta, Firebase, AWS Cognito, Keycloak) filtered strictly against `KNOWN_ROLES`.
   * **Secondary**: Firebase Admin SDK live lookup by email.
   * **Tertiary**: Server-side email mapping in `.env` (`ROLE_MAP_<role>=email`).
   * **Quaternary (Dev)**: `X-User-Roles` header when `REQUIRE_GOOGLE_AUTH=false`, strictly validated as a JSON array and sanitized against `KNOWN_ROLES`.
4. **Enterprise JWKS & Issuer Verification (`app/auth/jwks.py`)**:
   * Uses `verify_jwt_token()` with `get_allowed_issuers()` to support Google accounts, Firebase, and enterprise IdPs (`OIDC_JWKS_URI` and `OIDC_ISSUER`).
   * Performs pre-resolution issuer validation to prevent untrusted issuers from polluting the cached JWKS clients dictionary.
   * Enforces `leeway=60s` clock-skew tolerance per RFC 7519 to eliminate false `ImmatureSignatureError` rejections.

---

### Layer 3: High-Performance Ingestion Pipeline (scripts/ingest.py & libs/utilities.py)

The ingestion pipeline transforms raw documents into high-dimensional vector representations stored within the normalized PostgreSQL schema, enforcing change detection, semantic boundary preservation, and fault tolerance:

```mermaid
flowchart LR
    subgraph Stage1 ["1. Intake & Change Detection"]
        direction TB
        Raw["Raw Documents<br/>(PDF, MD, DOCX)"]
        Hash["SHA-256 Hashing<br/>(64KB Blocks)"]
        Check{"Exists in DB<br/>Same Hash?"}
        Skip["Skip Content<br/>(Zero Overhead)"]
        
        Raw --> Hash --> Check
        Check -->|Yes| Skip
    end

    subgraph Stage2 ["2. Chunking & Embedding"]
        direction TB
        Split["Semantic Split<br/>(512-800 Tokens)"]
        Meta["Attach Metadata<br/>(doc_id, index)"]
        Embed["Batch Embed<br/>(Tenacity Retry)"]
        
        Split --> Meta --> Embed
    end

    subgraph Stage3 ["3. Dual Persistence"]
        direction TB
        Master["Upsert Master &<br/>Purge Stale Chunks"]
        PG["PostgreSQL 16<br/>(HNSW + GIN)"]
        Azure["Azure AI Search<br/>(OData RBAC + HNSW)"]
        
        Master --> PG
        Master -.->|Sync| Azure
    end

    Check -->|Modified / New| Split
    Embed --> Master

    style Stage1 fill:#f8fafc,stroke:#94a3b8,stroke-width:1.5px
    style Stage2 fill:#f0f9ff,stroke:#0284c7,stroke-width:1.5px
    style Stage3 fill:#fdf4ff,stroke:#c026d3,stroke-width:1.5px
    style Skip fill:#fee2e2,stroke:#ef4444,stroke-width:1.5px
    style PG fill:#e0f2fe,stroke:#0369a1,stroke-width:1.5px
    style Azure fill:#fae8ff,stroke:#a21caf,stroke-width:1.5px
```

#### 1. Cryptographic SHA-256 De-duplication
* **Deterministic Change Detection**: Files are hashed in 64KB memory-safe chunks using SHA-256 (`compute_file_hash()`).
* **Instant B-Tree Lookup**: `check_document_exists(cur, filename, file_hash=file_hash)` leverages `idx_documents_file_hash` on `documents(file_hash)`.
* **Smart Update Routing**: Unchanged files are skipped with zero database or API overhead. Modified files (matching filename with divergent hash) trigger automatic re-indexing and replace previous chunks.
* **CLI Overrides**: Passing `--force` bypasses hash checks and forces end-to-end re-ingestion.

#### 2. Token-Aware Semantic Boundary Chunking
* **Tokenizer-Aligned Chunking**: Uses `RecursiveCharacterTextSplitter.from_tiktoken_encoder` (`model_name="text-embedding-3-large"`) with 512–800 token targets and 10–15% overlap (`chunk_size=800`, `chunk_overlap=100`).
* **Structure Preservation**: Structured separators (`\n## `, `\n### `, `\n#### `, `\n|`, `\n\n`) prevent breaking markdown section headers and table rows across chunk seams.
* **Metadata Attribution**: Automatically sets `page`, `chunk_index`, `source`, `document_id`, and `chunk_id` (`{document_id}_chunk_{index+1}`) on every chunk.

#### 3. Resilient Embeddings with Tenacity Backoff
* **Batch Slicing**: Chunks are processed in batches (default `batch_size=64`, configurable up to 128) to eliminate memory spikes and token limit exceptions.
* **Transient Error Retry**: Uses `tenacity` exponential backoff (`multiplier=1, min=2s, max=60s, attempts=5`) to automatically recover from OpenAI rate limits (`429`), timeouts, and gateway errors (`503`/`502`/`500`).

---

### Layer 4: RAG Quality, Hybrid Search & Grounding Guardrails

#### 1. Dense + Sparse Hybrid Search
While dense vector embeddings capture semantic intent, pure cosine similarity can miss exact alphanumeric identifiers, error codes (e.g. `ERR-502-BAD-GATEWAY`), and document IDs (`FIN-2026-001`). Sparse full-text search excels at exact lexical matching but misses semantic synonyms:

```
Dense Retrieval (HNSW Vector Index):
[Semantic Concepts & Intent] ────────► Cosine Similarity (1 - <=> )
                                                 │
                                                 ├─► Reciprocal Rank Fusion (RRF) ──► Top Candidates
                                                 │
Sparse Retrieval (GIN tsvector Index):           │
[Exact Terms, Identifiers, Codes] ───► Full-Text Rank (ts_rank)
```

#### 2. Reciprocal Rank Fusion (RRF) Algorithm
The hybrid pipeline evaluates both ranking algorithms and combines candidate items using the standard Reciprocal Rank Fusion formula:
$$RRF(d) = \sum_{m \in M} \frac{1}{k + rank_m(d)}$$
where $M = \{\text{dense}, \text{sparse}\}$, $k = 60$ is the standard smoothing constant, and $rank_m(d)$ represents the 1-based rank position in retrieval stream $m$.

Both retrieval queries strictly execute the same in-database RBAC filter (`d.allowed_roles ?| $user_roles::text[]`), guaranteeing that unauthenticated passages are excluded prior to scoring.

#### 3. Optional Cross-Encoder Re-Ranking (`libs/utilities.py`)
`rerank_candidates(query, candidates, top_k=5, cross_encoder_model=...)` evaluates the top candidates:
* **Deep Model (When Available)**: Uses sentence-transformers `CrossEncoder` or Cohere Rerank API to compute full cross-attention token interactions between `query` and `chunk.content`.
* **Deterministic Fallback**: In offline and test environments, applies a calibrated combination of semantic cosine similarity (50%), lexical token intersection (35%), and RRF position (15%).

#### 4. Strict Anti-Hallucination & Grounding Guardrails (`agent/guardrails.py`)
* **Standardized Citation Format**: Every claim in the LLM response must be attributed to an authorized passage in the format `[Doc: <Title>, Chunk <Index>]`.
* **Explicit Unknown Admission**: If the authorized context does not contain sufficient facts to answer the question, the assistant must explicitly declare:
  > *"I do not have sufficient information in the authorized documents to answer this question."*
* **GroundingGuardrail Validation**: `GroundingGuardrail.validate_response(answer, context_chunks)` evaluates regular expression citation patterns and verifies that cited document titles match genuine retrieved context passages.

---

### Layer 5: FastAPI Backend & Streamlit Streaming Frontend

#### 1. FastAPI Dependency Injection & Health Probes (`app/main.py`)
All endpoints enforce `get_current_user` with `leeway=60s` clock-skew tolerance and support Kubernetes container orchestration probes:
* `GET /healthz`: Immediate liveness check returning `{"status": "alive"}`.
* `GET /readyz`: Deep readiness check validating active PostgreSQL pool connection and pgvector extension availability (`SELECT extname FROM pg_extension WHERE extname = 'vector'`). Returns HTTP 503 if the database is unreachable.
* `POST /api/v1/query`: Accepts `RAGQueryRequest(question, mode="hybrid"|"dense")`. Applies zero-trust RBAC in PostgreSQL, runs RRF fusion, applies the grounding system prompt, and logs observability metrics.

#### 2. Real-Time Token Streaming in Streamlit (`streamlit_app.py`)
* Synchronous and asynchronous token generators (`chat_completion_stream`, `chat_completion_stream_sync`) stream LLM responses in real-time.
* Uses Streamlit's native `st.write_stream(...)` to render response tokens as they arrive, eliminating perceived latency while maintaining expanders for citations and executed RBAC SQL queries.

#### 3. Shared Connection Pooling (`@st.cache_resource`)
Streamlit creates new script runner threads per user interaction. To prevent PostgreSQL connection pool exhaustion:
* `get_shared_db_pool()` is decorated with `@st.cache_resource`, ensuring a single shared connection pool persists across all sessions and page refreshes.

#### 4. Thread-Safe Async Runner (`run_async`)
* Protects against `RuntimeError: This event loop is already running` in multi-threaded Streamlit worker threads.
* Automatically detects active event loops, applies `nest_asyncio` if present, and routes execution to an isolated `concurrent.futures.ThreadPoolExecutor` when called inside an already-active event loop.

---

### Layer 6: Observability, Distributed Tracing & Container Hardening

#### 1. Configuration Validation via Pydantic BaseSettings (`app/config.py`)
`app/config.py` uses `pydantic_settings.BaseSettings` to validate environment variables, secrets, and connection parameters at application startup. Missing credentials or malformed URIs fail fast during boot rather than intermittently at runtime.

#### 2. Distributed Tracing Architecture & OpenTelemetry Engine
The platform implements full-stack distributed tracing via **OpenTelemetry (OTel)** using the **OTLP gRPC Exporter** (`http://localhost:4317`) streaming spans into a persistent **Jaeger All-In-One** backend.

```mermaid
flowchart LR
    subgraph Sources ["1. Trace Producers"]
        direction TB
        Browser["User Browser<br/>(Client Session)"]
        UI["Streamlit UI<br/>(Port :8501)"]
        API["FastAPI Gateway<br/>(Port :8000)"]
        MCP["FastMCP Server<br/>(app/mcp)"]
        LLM["LLM Service<br/>(OpenAI / Azure)"]

        Browser -->|chat_interaction| UI
        UI -->|http_request| API
        UI -->|mcp_tool| MCP
        API -->|rag.generate| LLM
    end

    subgraph Core ["2. Telemetry Engine"]
        OTel["OpenTelemetry SDK<br/>(app/observability.py)<br/>• BatchSpanProcessor<br/>• Standard Semantic Tags"]
    end

    subgraph Sinks ["3. Tracing Backends"]
        direction TB
        Jaeger["Jaeger All-In-One<br/>• OTLP gRPC (:4317)<br/>• Persistent Badger LSM<br/>• Web UI (:16686)"]
        AppInsights["Azure App Insights<br/>• Managed Azure Monitor<br/>• Cloud Dashboard"]
    end

    Sources ==>|OTLP Spans| OTel
    OTel -->|Local Jaeger| Jaeger
    OTel -->|Azure Monitor| AppInsights

    style Sources fill:#f8fafc,stroke:#94a3b8,stroke-width:1.5px
    style Core fill:#f0fdf4,stroke:#16a34a,stroke-width:1.5px
    style Sinks fill:#f0f9ff,stroke:#0284c7,stroke-width:1.5px
    style Jaeger fill:#fefce8,stroke:#ca8a04,stroke-width:1.5px
    style AppInsights fill:#fdf4ff,stroke:#c026d3,stroke-width:1.5px
```

##### Telemetry Configuration & Ports
| Component | Port | Protocol | Purpose |
| :--- | :--- | :--- | :--- |
| **Jaeger UI** | `16686` | HTTP | Web UI trace search, dependency graph, and timeline inspection |
| **OTLP gRPC** | `4317` | gRPC | Standard OpenTelemetry span ingestion endpoint |
| **OTLP HTTP** | `4318` | HTTP | Alternative OTLP HTTP ingestion endpoint |
| **FastAPI** | `8000` | HTTP | REST API & Interactive Documentation (`/docs`) |
| **Streamlit** | `8501` | HTTP | Enterprise UI frontend |
| **PostgreSQL / pgvector** | `5432` | TCP | RBAC metadata and vector embeddings |

##### Standardized Span Attributes & Events
All spans comply with OpenTelemetry semantic conventions extended with enterprise RAG tags:
* **Session & Identity**: `user.id`, `user.role`, `user.clearance`, `session.id`
* **RAG Flow**: `rag.question`, `rag.response`, `rag.source_count`, `rag.processing_time_ms`, `rag.model`
* **MCP / Tools**: `mcp.tool_name`, `mcp.status`, `mcp.duration_ms`, `mcp.args`
* **HTTP Spans**: `http.method`, `http.url`, `http.status_code`, `http.duration_ms`
* **Recorded Events**:
  * `query_received`: Logged on initial request reception.
  * `retrieval_completed`: Logged with document IDs and vector distance scores.
  * `generation_completed`: Logged upon final output synthesis.
  * `query_processed`: Logged with full list of cited document sources.
  * `tool_completed`: Logged with tool result payload previews.

#### 3. Cross-Service Instrumentation Implementations

##### Core Observability Engine (`app/observability.py`)
A centralized tracing manager handles provider lifecycle with graceful fallback to a `NoOpTracer` if Jaeger is unavailable, paired with an in-memory bounded ring buffer (last 1,000 events) accessible via `GET /api/v1/metrics/observability`:

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
import time
from typing import Dict, Any

def setup_observability(service_name: str = "enterprise-rag") -> trace.Tracer:
    """Configures OpenTelemetry tracer provider with OTLP gRPC export."""
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    try:
        processor = BatchSpanProcessor(OTLPSpanExporter(endpoint="localhost:4317", insecure=True))
        provider.add_span_processor(processor)
    except Exception:
        pass
    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)

def record_chat_interaction(
    tracer: trace.Tracer,
    user_id: str,
    user_role: str,
    question: str,
    response: str,
    sources: list,
    duration_ms: float
):
    """Generates a dedicated parent span recording full RAG query/response context."""
    with tracer.start_as_current_span("chat_interaction") as span:
        span.set_attribute("user.id", user_id)
        span.set_attribute("user.role", user_role)
        span.set_attribute("rag.question", question)
        span.set_attribute("rag.response", response)
        span.set_attribute("rag.source_count", len(sources))
        span.set_attribute("rag.processing_time_ms", duration_ms)
        span.add_event("query_processed", {
            "sources": str([s.get("source", "unknown") for s in sources])
        })
```

##### FastAPI HTTP Middleware (`app/main.py`)
Inbound HTTP requests automatically generate traced spans capturing client methods, routes, status codes, and execution latency:

```python
import time
from fastapi import FastAPI, Request
from app.observability import setup_observability

app = FastAPI(title="Enterprise RAG Service")
tracer = setup_observability("rag-fastapi")

@app.middleware("http")
async def trace_requests(request: Request, call_next):
    start_time = time.time()
    with tracer.start_as_current_span(f"http_{request.method}_{request.url.path}") as span:
        span.set_attribute("http.method", request.method)
        span.set_attribute("http.url", str(request.url))
        try:
            response = await call_next(request)
            span.set_attribute("http.status_code", response.status_code)
            return response
        except Exception as exc:
            span.record_exception(exc)
            span.set_attribute("http.status_code", 500)
            raise exc
        finally:
            span.set_attribute("http.duration_ms", (time.time() - start_time) * 1000)
```

##### FastMCP Gateway Tracing (`app/mcp/gateway.py`)
Every tool execution within the FastMCP gateway is wrapped with trace span capture:

```python
import time
from app.observability import setup_observability, record_mcp_tool_execution

mcp_tracer = setup_observability("rag-mcp-server")

async def execute_tool_wrapper(tool_name: str, **kwargs):
    start_time = time.time()
    status = "success"
    try:
        result = await dispatch_tool(tool_name, **kwargs)
        return result
    except Exception as exc:
        status = "error"
        raise exc
    finally:
        duration_ms = (time.time() - start_time) * 1000
        record_mcp_tool_execution(
            tracer=mcp_tracer,
            tool_name=tool_name,
            arguments=kwargs,
            result=result if status == "success" else None,
            duration_ms=duration_ms,
            status=status
        )
```

#### 4. Persistent Jaeger Storage Architecture (Badger LSM-Tree)
By default, Jaeger `all-in-one` stores spans in ephemeral container memory, purging all traces on container restart.
* **Badger Engine**: Setting `SPAN_STORAGE_TYPE=badger` enables an embedded, persistent Log-Structured Merge-tree (LSM) key-value store backed by Docker named volumes.
* **Permission Hardening (`user: "0:0"`)**: Jaeger defaults to running as UID `10001` (`jaeger`), which causes a fatal initialization failure (`mkdir /badger/key: permission denied`) against root-owned host mounts. Declaring `user: "0:0"` grants the container write permissions to create `/badger/data` and `/badger/key`.
* **Image Naming Note**: Use `jaegertracing/all-in-one:latest` (or official tags like `v1.76.0`); `jaegertracing/jaeger:2` is not published under that tag on Docker Hub.

```yaml
version: "3.8"

services:
  jaeger:
    image: jaegertracing/all-in-one:latest
    container_name: jaeger
    user: "0:0"
    environment:
      - SPAN_STORAGE_TYPE=badger
      - BADGER_EPHEMERAL=false
      - BADGER_DIRECTORY_VALUE=/badger/data
      - BADGER_DIRECTORY_KEY=/badger/key
      - BADGER_SPAN_STORE_TTL=168h # 7-day retention
    ports:
      - "16686:16686" # Web UI
      - "4317:4317"   # OTLP gRPC Ingestion
      - "4318:4318"   # OTLP HTTP Ingestion
      - "14268:14268" # jaeger.thrift ingestion
    volumes:
      - jaeger_data:/badger
    restart: unless-stopped

  postgres:
    image: pgvector/pgvector:pg16
    container_name: enterprise-rag-db
    environment:
      POSTGRES_USER: rag_user
      POSTGRES_PASSWORD: rag_password
      POSTGRES_DB: enterprise_rag
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    restart: unless-stopped

volumes:
  jaeger_data:
    driver: local
  pgdata:
    driver: local
```

#### 5. Hardened Multi-Stage Dockerfile (`Dockerfile`)
```dockerfile
# Stage 1: Build & Wheel Compilation
FROM python:3.11-slim AS builder
RUN pip install --no-cache-dir --user -r requirements.txt

# Stage 2: Hardened Runtime Container
FROM python:3.11-slim AS runner
RUN groupadd -g 10001 appgroup && useradd -u 10001 -g appgroup -m -s /bin/bash appuser
USER appuser
HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:8000/healthz || exit 1
```
* **Minimal Attack Surface**: Build dependencies (`gcc`, `libpq-dev`) are stripped from the final runtime image.
* **Non-Root Execution**: Runs under unprivileged user `appuser` (UID 10001), preventing container escape vulnerabilities.

#### 6. Automated Integration Testing (`testcontainers-python`)
`tests/test_integration_pgvector.py` provides end-to-end integration testing against real database containers (`pgvector/pgvector:pg16`), verifying that `schema.sql` initializes extensions, creates tables, and executes HNSW and GIN queries accurately in CI environments.


---

### Layer 7: FastMCP Agent Gateway (app/mcp/)

FastMCP standardizes tool and resource access for external AI coding agents (Claude Desktop, Cursor, CLI agents):

| Primitive | Signature | Function |
| :--- | :--- | :--- |
| **Tool** | `search_sdlc_context(question, auth_token, user_roles)` | Authenticates calling agent via Google ID token and returns in-database RBAC-filtered knowledge base snippets. |
| **Tool** | `propose_patch(branch_name, patch_content, auth_token)` | Validates submitter identity and writes unified diff modifications to a feature branch. |
| **Resource** | `policy://sdlc-budget` | Serves operational constraints: maximum tokens per issue (`50,000`), maximum execution steps (`10`), and allowed tools. |

---

### Layer 8: Autonomous Self-Healing SDLC Agent (agent/)

The autonomous agent listens to GitHub issue webhooks, writes code patches, audits them statically, runs tests, and autonomously repairs bugs:

```mermaid
flowchart LR
    subgraph Intake ["1. Webhook & Init"]
        direction TB
        Hook["GitHub Issue Webhook<br/>(HMAC-SHA256 Verified)"]
        Init["Initialize State<br/>& Checkout Branch"]
        Hook --> Init
    end

    subgraph Gen ["2. Patch Synthesis"]
        direction TB
        Propose["Propose Patch<br/>(Targeted LLM Prompt)"]
        Apply["Apply to Sandbox<br/>(Path Traversal Guard)"]
        Propose --> Apply
    end

    subgraph Audit ["3. Security Gate"]
        direction TB
        Inspect["AST & Secret Audit<br/>(eval, exec & key checks)"]
        Reject["Policy Violation<br/>(Execution Blocked)"]
        Inspect -->|Failed| Reject
    end

    subgraph Verify ["4. Test & Self-Healing"]
        direction TB
        Test{"Run Pytest<br/>Offline Suite"}
        Repair["Repair Patch<br/>(Traceback Injected)"]
        Escalate["Max Retries (3)<br/>(Escalate to Human)"]

        Test -->|Failed: Retries < 3| Repair
        Test -->|Failed: Retries >= 3| Escalate
    end

    subgraph Done ["5. PR Delivery"]
        PR["Clean Git Commit<br/>& Open Pull Request"]
    end

    Init --> Propose
    Apply --> Inspect
    Inspect -->|Passed| Test
    Repair --> Apply
    Test -->|Tests Passed| PR

    style Intake fill:#f8fafc,stroke:#94a3b8,stroke-width:1.5px
    style Gen fill:#f0f9ff,stroke:#0284c7,stroke-width:1.5px
    style Audit fill:#fefce8,stroke:#ca8a04,stroke-width:1.5px
    style Verify fill:#fdf4ff,stroke:#c026d3,stroke-width:1.5px
    style Done fill:#f0fdf4,stroke:#16a34a,stroke-width:1.5px
    style Reject fill:#fee2e2,stroke:#ef4444,stroke-width:1.5px
    style Escalate fill:#fee2e2,stroke:#ef4444,stroke-width:1.5px
    style PR fill:#dcfce7,stroke:#22c55e,stroke-width:1.5px
```

#### LangGraph Workflow Nodes (`agent/workflow.py`)
1. **`initialize`**: Verifies the webhook HMAC signature (`X-Hub-Signature-256`), checks out a clean Git branch (`feature/AGENT-<id>-<slug>`), and initializes `AgentState`.
2. **`propose_patches`**: Prompts the LLM to generate targeted patch proposals (`file_path`, `content`).
3. **`apply_patches`**: Writes code while strictly enforcing **Sandbox Path Traversal Defenses** (rejects absolute paths, `..`, and `.git/`).
4. **`audit_patches`**: Executes deterministic security guardrails before code execution.
5. **`run_tests`**: Runs `pytest` in a background subprocess (`asyncio.to_thread`).
6. **`repair_patches` (Self-Healing Loop)**: If tests fail, slices the trailing 2,500 characters of error traceback into the LLM repair prompt, regenerates patches, and re-tests (up to `max_attempts=3`).
7. **`finalize`**: Commits verified code and opens a pull request with an embedded security audit summary.

#### Deterministic Security Guardrails (`agent/guardrails.py`)
* **Secret Scanning**: Compiled regex filters flag OpenAI keys (`sk-...`), private keys (`-----BEGIN PRIVATE KEY-----`), and Google API keys (`AIza...`).
* **AST Code Inspection**: Uses Python's `ast.walk()` to block execution sinks (`eval()`, `exec()`, `__import__()`) without executing untrusted code.

---

## Threat Model & Security Architecture (STRIDE)

| Threat Category | Potential Attack Vector | Platform Mitigation & Invariant |
| :--- | :--- | :--- |
| **Spoofing** | Forged JWT identity tokens | Cryptographic signature verification via cached JWKS public keys (`RS256`, `leeway=60s`). |
| **Tampering** | In-flight payload manipulation | TLS 1.3 encryption, SHA-256 PKCE code challenges, and HMAC-SHA256 state/cookie signing. |
| **Repudiation** | Unaudited data access | OpenTelemetry distributed tracing recording tenant ID, user ID, and roles for every query. |
| **Information Disclosure** | Vector database memory snooping | **In-database Zero-Trust filtering**: unauthorized records are never loaded into RAM. |
| **Denial of Service** | Expensive unbounded vector scans | Connection pooling, query timeouts (`5000ms`), and indexed HNSW graphs. |
| **Elevation of Privilege**| LLM prompt injection manipulating roles | Hardened role boundaries extracted exclusively from signed JWT claims and `KNOWN_ROLES`. |

---

## 5-Minute Quickstart

### 1. Environment Setup
```powershell
# Clone repository
git clone https://github.com/Kenono2000/enterprise-rag-pgvector-rbac.git
cd enterprise-rag-pgvector-rbac

# Create isolated virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### 2. Run Automated Verification (110 Tests)
All tests run **100% offline** with zero external network or API dependencies:
```powershell
python -m pytest -v
```

### 3. Launch Services
```powershell
# Start PostgreSQL 16 + pgvector and Persistent Jaeger Tracing
docker compose up -d

# Initialize PostgreSQL schema, extensions, and mock records (if running native psql)
psql -U postgres -d enterprise_rag -f schema.sql

# Start FastAPI Microservice (Port 8000)
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
# 📖 Swagger UI: http://localhost:8000/docs
# 🩺 Health Probes: http://localhost:8000/healthz | http://localhost:8000/readyz
# 📊 Metrics Snapshot: http://localhost:8000/api/v1/metrics/observability

# Start Streamlit UI (Port 8501)
python -m streamlit run streamlit_app.py --server.port 8501
# 🖥️ Web App: http://localhost:8501

# Inspect Distributed Tracing & RAG Question/Response in Jaeger (Port 16686)
# 🔍 Jaeger UI: http://localhost:16686 (Service: enterprise-rag-pgvector-rbac)

# Start FastMCP Gateway
python -m app.mcp
```

---

## Testing & Verification Guide (110 Tests: 109 Passed, 1 Skipped)

```text
tests/test_agent.py                     ......                                           [  5%]
tests/test_auth.py                      ..................................               [ 36%]
tests/test_azure_search.py              ...                                              [ 39%]
tests/test_database_schema.py           ......                                           [ 44%]
tests/test_hybrid_search.py             ......                                           [ 50%]
tests/test_ingest.py                    .........                                        [ 58%]
tests/test_integration_pgvector.py      s.                                               [ 60%]
tests/test_mcp_auth.py                  ..........                                       [ 69%]
tests/test_multicloud_search.py         ........                                         [ 76%]
tests/test_observability_and_health.py  ........                                         [ 83%]
tests/test_rag.py                       ....                                             [ 87%]
tests/test_security_rbac.py             .....                                            [ 91%]
tests/test_utilities.py                 .......                                          [100%]
================== 109 passed, 1 skipped, 2 warnings in 41.82s ===================
```

### Test Suite Breakdown

| Module | Tests | Key Invariants Verified |
| :--- | :---: | :--- |
| **`tests/test_azure_search.py`** | 3 | • Zero-Trust short circuiting when `user_roles` is empty.<br/>• OData collection RBAC filter (`allowed_roles/any(...)`) syntax.<br/>• Dynamic routing to Azure AI Search when `RETRIEVAL_BACKEND="azure"`. |
| **`tests/test_multicloud_search.py`** | 8 | • Google Cloud Vertex AI Vector Search Restricts pre-filtering (`allowed_roles`).<br/>• Databricks Mosaic AI Vector Search Unity Catalog filters (`filters_json`).<br/>• Dynamic runtime dispatch in `app/main.py` and `app/mcp/gateway.py`.<br/>• Zero-Trust empty role immediate return invariant. |
| **`tests/test_hybrid_search.py`** | 6 | • Reciprocal Rank Fusion (RRF) math validation.<br/>• Zero-Trust empty role short-circuiting.<br/>• Heuristic & cross-encoder candidate re-ranking.<br/>• GroundingGuardrail citation and missing context admission checks. |
| **`tests/test_observability_and_health.py`** | 7 | • Liveness (`/healthz`) and readiness (`/readyz`) probes.<br/>• Telemetry endpoint (`/api/v1/metrics/observability`).<br/>• 503 DB failure handling.<br/>• Pydantic `BaseSettings` validation.<br/>• `ObservabilityTracer` metric recording.<br/>• Token streaming sync and async generators. |
| **`tests/test_integration_pgvector.py`** | 2 | • Testcontainers `pgvector/pgvector:pg16` end-to-end integration harness.<br/>• Verification of schema.sql DDL, HNSW index, and GIN full-text search. |
| **`tests/test_database_schema.py`** | 6 | • Normalized table schemas (`documents` & `document_chunks`).<br/>• `ON DELETE CASCADE` foreign key relationship.<br/>• HNSW vector index (`m=16, ef=64`) & GIN role index.<br/>• GIN full-text index on `tsv`.<br/>• B-tree file hash de-duplication index.<br/>• Cosine similarity calculation benchmark simulation. |
| **`tests/test_security_rbac.py`** | 5 | • SQL injection immunity in vector search.<br/>• Parameterized array containment (`$2::text[]`).<br/>• Zero-Trust empty role short-circuiting.<br/>• Header validation and injection filtering. |
| **`tests/test_auth.py`** | 34 | • RFC 7636 PKCE `code_verifier` & `code_challenge` derivation.<br/>• Stateless HMAC-SHA256 OAuth state generation & expiration (300s TTL).<br/>• Google JWKS certificate caching & `leeway=60s` clock skew tolerance.<br/>• Multi-source role claim extraction (`app_roles`, `roles`, `groups`, `cognito:groups`, `realm_access.roles`).<br/>• Enterprise JWKS issuer validation & rejection of untrusted issuers.<br/>• **Session Cookie Encoding**: Roundtrip compression, signature tampering rejection, expired TTL handling, and malformed cookie rejection. |
| **`tests/test_rag.py`** | 4 | • Health check status.<br/>• Strict 401 rejection when unauthenticated.<br/>• Dev header fallback (`X-User-Roles`).<br/>• End-to-end vector retrieval & RBAC filtering. |
| **`tests/test_mcp_auth.py`** | 11 | • FastMCP token validation and unauthenticated caller rejection.<br/>• Verified role extraction from ID tokens for tool execution.<br/>• Identity verification on patch submission.<br/>• Multi-transport server verification (stdio, SSE). |
| **`tests/test_agent.py`** | 6 | • GitHub webhook HMAC-SHA256 verification.<br/>• Webhook JSON parsing into typed models.<br/>• Deterministic secret scanning (API keys, private keys).<br/>• AST static inspection (`eval`, `exec`, `__import__`).<br/>• Sandbox path traversal prevention.<br/>• Full LangGraph self-healing test repair cycle. |
| **`tests/test_ingest.py`** | 9 | • Pre-ingestion SHA-256 de-duplication, modified file re-indexing detection, force flag bypass, stem matching, chunk prefix detection. |
| **`tests/test_utilities.py`** | 7 | • Multi-format loaders (`.pdf`, `.md`, `.docx`), tokenizer-aware chunk splitting, chunk metadata attribution, 64KB block hashing, and tenacity retry on 429 rate limits. |
| **Total** | **110** | **109 Passed, 1 Skipped** |

---

## Solved Engineering Pitfalls & Root Cause Analysis

| Symptom / Error | Root Cause | Permanent Engineering Solution |
| :--- | :--- | :--- |
| **SQL Injection in RBAC Filtering** | String-formatting user roles into SQL queries (`ARRAY[...]`). | **Parameterized Bindings & Sanitization**: Bound roles to `$2::text[]` via asyncpg, added zero-trust short-circuit on empty roles, and sanitized claims against `KNOWN_ROLES`. |
| **Sparse Alphanumeric Misses in Pure Vector Search** | Pure cosine similarity can miss exact identifiers, error codes, and technical names. | **Hybrid Search & Reciprocal Rank Fusion (RRF)**: Merges dense vector HNSW cosine similarity and sparse GIN `ts_rank` via $RRF(d) = \sum \frac{1}{60 + rank(d)}$. |
| **LLM Hallucinations & Ungrounded Claims** | Unconstrained prompts hallucinate missing context. | **GroundingGuardrails**: Strict system prompt enforcing citations (`[Doc: <Title>, Chunk <Index>]`) and automated AST/regex validation admitting unknown facts when context is absent. |
| **Streamlit Worker Event Loop Collisions** | Calling async coroutines in Streamlit worker threads collided with active event loops. | **Thread-Safe Async Runner**: Centralized runner applying `nest_asyncio` with isolated `ThreadPoolExecutor` fallback. |
| **Connection Pool Exhaustion** | Re-creating connections per query under concurrent traffic exhausted PostgreSQL. | **Cached Connection Pool**: Decorated `get_shared_db_pool()` with `@st.cache_resource` to share pooled connections safely across sessions. |
| **Ingestion Duplication & Edits Missed** | Filename-only prefix checks missed file edits and duplicated renamed files. | **Cryptographic SHA-256 De-duplication**: 64KB block hashing with change detection skips identical files and purges obsolete chunk sets on re-indexing. |
| **Embedding API Rate Limits (429/503)** | Unbatched or unprotected embedding requests hit provider rate limits. | **Tenacity Exponential Backoff & 64-Item Batching**: Batch-embeds 64–128 items with automated exponential backoff (2s–60s) on transient 429/503 errors. |
| **Container Orchestrator Probes Missing** | Kubernetes clusters lacked standardized health and readiness endpoints. | **`/healthz` & `/readyz` Endpoints**: Implemented liveness and deep readiness probes verifying database reachability and vector extension presence. |
| **Configuration Drift & Missing Secrets** | Unvalidated environment variables failed deep in execution runtime. | **Pydantic `BaseSettings`**: Centralized startup validation in `app/config.py` rejecting invalid environments immediately. |
| **OAuth state mismatch / CSRF** | Streamlit re-creates session on navigation away to Google. | **Stateless HMAC-SHA256 Signed State**: Verifier is embedded in signed state string; zero server memory dependency. |
| **Browser reload requires re-login (F5)** | Streamlit WebSocket reset clears RAM session state. | **Encrypted Session Cookie**: `enterprise_rag_session` cookie is written to browser and rehydrated via `st.context.cookies`. |
| **`ImmatureSignatureError: (iat)`** | Clock drift between local machine and Google NTP servers. | Added `leeway=60` in `jwt.decode()` per RFC 7519. |
| **`RuntimeError: Event loop is closed`** | Streamlit tears down async event loops between reruns while `AsyncOpenAI` retained transport connections bound to the initial loop. | **Loop-Scoped Client Manager**: Scopes `AsyncOpenAI` and `asyncpg` pools dynamically to active event loops (`get_openai_client()`), re-initializing cleanly if the prior loop is closed. |
| **Context Eviction / Recall Starvation** | Post-filtering in application code drops top-$K$ restricted documents. | **In-Database RBAC**: Evaluates `WHERE allowed_roles ?| $user_roles` inside PostgreSQL before vector distance ranking. |
| **`NameError: name 'json' is not defined`** | Missing top-level import in `streamlit_app.py` during debug metadata extraction. | Added `import json` to top-level module imports. |
| **Grounding Refusals on Synthetic Summaries** | Overly strict prompt penalties caused false refusals when questions didn't match documents verbatim. | **Grounding Calibration**: Calibrated prompt to distinguish semantic cross-excerpt synthesis from absent facts. |
| **FastAPI / OpenTelemetry Dependency Conflict** | `fastapi==0.142.2` requires `opentelemetry-api>=1.44.0`, colliding with older pinned builds. | Pinned `opentelemetry-api>=1.45.1`, `opentelemetry-sdk>=1.45.1`, and `opentelemetry-exporter-otlp>=1.45.1`. |
| **Jaeger Badger `mkdir /badger/key: permission denied`** | Docker mounts root-owned named volume while container ran as non-root user. | **Container User Mapping (`user: "0:0"`)**: Run Jaeger with root user context to initialize Badger LSM value log directories and SSTable index keys. |
| **Jaeger Trace Loss on Container Restart** | Default all-in-one image stores traces in ephemeral memory. | **Persistent Badger Storage**: Configured `SPAN_STORAGE_TYPE=badger` with Docker volume `jaeger_data:/badger` and 7-day TTL retention. |

---

### Root Cause Analysis & Deep Dives

#### 8.1. Concurrency: `RuntimeError: Event loop is closed`
* **Symptom**: Repeated requests in Streamlit crashed with:
  `RuntimeError: Event loop is closed` at `openai/_base_client.py:1532`.
* **Root Cause**: An `AsyncOpenAI` client was declared as a global singleton at module import time in `app/db/llm.py`. Streamlit runs user interactions across varying thread pools. When a thread terminates its asyncio event loop, the global client's internal HTTPX connection pool retains references to the destroyed loop, triggering an immediate crash on subsequent calls.
* **Resolution**: Implemented thread/loop-scoped client management via `get_openai_client()`:

```python
import asyncio
from openai import AsyncOpenAI
from typing import Dict

_openai_clients: Dict[asyncio.AbstractEventLoop, AsyncOpenAI] = {}

def get_openai_client() -> AsyncOpenAI:
    """Returns an AsyncOpenAI client bound to the current thread's active event loop."""
    loop = asyncio.get_running_loop()
    if loop not in _openai_clients:
        _openai_clients[loop] = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _openai_clients[loop]
```

#### 8.2. Scope Bug: `NameError: name 'json' is not defined`
* **Symptom**: Chat query submission in Streamlit threw `NameError: name 'json' is not defined` inside `streamlit_app.py`.
* **Root Cause**: `json.dumps()` was invoked during debug metadata extraction without an explicit top-level `import json` statement.
* **Resolution**: Added `import json` to top-level imports in `streamlit_app.py`.

#### 8.3. Grounding System Prompt Calibration
* **Symptom**: Legitimate questions regarding general repository policies or broad document summaries resulted in abrupt generic refusals: *"I do not have sufficient information in the provided context to answer your question."*
* **Root Cause**: Overly strict prompt penalties caused the model to reject queries when documents didn't match the query wording with 100% lexical precision.
* **Resolution**: Calibrated system prompt to distinguish between *absence of data* and *semantic synthesis of retrieved excerpts*:

```text
You are an enterprise AI assistant for document retrieval and question answering.
Answer the user's question based strictly on the provided context excerpts.
Synthesize information across multiple excerpts if relevant.
Do not speculate or extrapolate beyond the provided text.
If the provided context does not contain any facts relevant to answering the question,
state clearly: "I do not have sufficient information in the provided context to answer your question."
Always cite your sources using the format [Document Name, Page/Section].
```

#### 8.4. Dependency Incompatibility & Version Pinning
* **Symptom**: `pip install` failures and runtime import errors between FastAPI and OpenTelemetry.
* **Root Cause**: `fastapi==0.142.2` enforces `opentelemetry-api>=1.44.0`, whereas local environment was pinned to an older sub-1.40.0 build.
* **Resolution**: Updated `requirements.txt`:
  ```text
  opentelemetry-api>=1.45.1
  opentelemetry-sdk>=1.45.1
  opentelemetry-exporter-otlp>=1.45.1
  ```

#### 8.5. Persistent Jaeger Storage & Docker Volume Permissions
* **Symptom**: Jaeger failed to start when switching from in-memory to Badger storage:
  > `{"level":"fatal","caller":"all-in-one/main.go:105","msg":"Failed to init storage factory","error":"Error Creating Dir: \"/badger/key\" err: mkdir /badger/key: permission denied"}`
* **Root Cause**: The Jaeger container defaults to non-root user `jaeger` (UID `10001`), which lacks write permissions to host-mounted named volumes.
* **Resolution**: Explicitly declare `user: "0:0"` in `docker-compose.yml` to run the container as root and mount named volume `jaeger_data:/badger`.

---

## Incident Response, Operational Runbook & Jaeger Persistence Verification

```mermaid
flowchart LR
    subgraph Detection ["1. Detection"]
        direction TB
        Alert["Alert Triggered<br/>(OTel / AppInsights)"]
        Trace["Trace Analysis<br/>(Inspect Traceparent)"]
        Alert --> Trace
    end

    subgraph Triage ["2. Triage"]
        direction TB
        ErrorClass{"Error Type?"}
        DBErr["Database / Latency"]
        AuthErr["Authentication Fail"]
        ErrorClass --> DBErr
        ErrorClass --> AuthErr
    end

    subgraph Remediation ["3. Remediation"]
        direction TB
        Action1["Switch Backend<br/>(RETRIEVAL_BACKEND)"]
        Action2["Rotate JWKS Cache<br/>(Flush Memory Lock)"]
        DBErr --> Action1
        AuthErr --> Action2
    end

    Detection --> Triage
    Triage --> Remediation

    style Detection fill:#f8fafc,stroke:#94a3b8,stroke-width:1.5px
    style Triage fill:#fef3c7,stroke:#d97706,stroke-width:1.5px
    style Remediation fill:#dcfce7,stroke:#22c55e,stroke-width:1.5px
```

### 9.1. Incident Response Playbooks

#### Scenario A: Database Node Outage or Latency Spike
1. Inspect active spans in Jaeger (`http://localhost:16686`) or Azure Application Insights.
2. Toggle backend to Azure AI Search (or GCP / Databricks) in [`.env`](file:///c:/src/enterprise-rag-pgvector-rbac/.env):
   ```ini
   RETRIEVAL_BACKEND="azure"
   ```
3. Restart FastAPI worker:
   ```powershell
   uvicorn app.main:app --port 8000 --reload
   ```

#### Scenario B: JWKS Key Rotation Failure
1. Check identity provider reachability (`https://www.googleapis.com/oauth2/v3/certs`).
2. Force-refresh JWKS cache by restarting the auth worker or clearing `JWKSClient._cache`.
3. Validate token verification with the test suite:
   ```powershell
   python -m pytest tests/test_auth.py -k "test_jwks" -v
   ```

### 9.2. Running the Automated Test Suite
Run unit and integration tests covering RBAC, document chunking, embeddings, vector retrieval, multi-cloud routing, and tracing hooks:

```powershell
python -m pytest -v
```

**Verification Results**:
* Total Tests: **110**
* Passed: **109**
* Skipped: **1** (Live container mock fallback)
* Test Duration: ~41.8s

### 9.3. Container Orchestration & Health Checks

```powershell
# 1. Stop existing containers
docker compose down

# 2. Re-create and start with persistent volumes
docker compose up -d

# 3. Verify container status
docker compose ps
```

Expected Output:
```text
NAME                 IMAGE                         STATUS         PORTS
enterprise-rag-db    pgvector/pgvector:pg16        Up (healthy)   0.0.0.0:5432->5432/tcp
jaeger               jaegertracing/all-in-one      Up             0.0.0.0:4317-4318->4317-4318/tcp, 0.0.0.0:16686->16686/tcp
```

### 9.4. Verifying Trace Persistence in Jaeger
1. Open `http://localhost:16686` in a browser.
2. Under **Service**, select `enterprise-rag-pgvector-rbac` or `rag-fastapi`.
3. Submit a query via Streamlit (`http://localhost:8501`) or execute an API call via Swagger (`http://localhost:8000/docs`).
4. Click **Find Traces** in Jaeger UI; inspect the `chat_interaction` span and expand `Tags` to inspect `rag.question` and `rag.response`.
5. Restart the Jaeger container:
   ```powershell
   docker compose restart jaeger
   ```
6. Refresh `http://localhost:16686` and re-run search. **All previous traces remain intact and searchable from Badger disk storage.**

---

## Multi-Cloud Migration Playbook & Architecture (Azure, GCP, Databricks)

For organizations deploying across hybrid and multi-cloud environments, the platform includes a **Quad-Mode Multi-Cloud Backend** allowing zero-downtime runtime switching between:
- **PostgreSQL (`pgvector`)**: Local / On-prem / Cloud SQL / Aurora
- **Microsoft Azure AI (`azure`)**: Azure AI Search (HNSW + Bing Semantic Ranker) + Azure OpenAI Service + Azure Application Insights
- **Google Cloud Platform (`gcp`)**: Vertex AI Vector Search (ScaNN / Tree-AH) + Gemini API
- **Databricks Lakehouse (`databricks`)**: Mosaic AI Vector Search + Unity Catalog Delta Lake

```mermaid
flowchart LR
    subgraph Provisioning ["1. Cloud Provisioning"]
        direction TB
        Azure_P["Phase 1A:<br/>Azure AI Search<br/>(HNSW + Semantic)"]
        GCP_P["Phase 1B:<br/>Google Vertex AI<br/>(ScaNN Restricts)"]
        DBX_P["Phase 1C:<br/>Databricks Mosaic<br/>(Unity Catalog)"]
    end

    subgraph DataOps ["2. Data Pipeline"]
        direction TB
        MIG["Phase 2:<br/>Batch Migration<br/>(PostgreSQL Chunks)"]
        VAL["Phase 3:<br/>Index Validation<br/>(RBAC Pre-Filters)"]
        MIG --> VAL
    end

    subgraph Cutover ["3. Routing & Cutover"]
        direction TB
        ENV["Phase 4:<br/>Switch Backend<br/>(.env Toggle)"]
        TEST["Phase 5:<br/>Automated Tests<br/>(pytest Suite)"]
        ENV --> TEST
    end

    Provisioning --> DataOps
    DataOps --> Cutover

    style Provisioning fill:#f8fafc,stroke:#94a3b8,stroke-width:1.5px
    style DataOps fill:#f0f9ff,stroke:#0284c7,stroke-width:1.5px
    style Cutover fill:#dcfce7,stroke:#22c55e,stroke-width:1.5px
```

### 1. Architectural Component Mapping Across Clouds

| Function | PostgreSQL (`pgvector`) | Microsoft Azure AI (`azure`) | Google Cloud (`gcp`) | Databricks (`databricks`) |
| :--- | :--- | :--- | :--- | :--- |
| **Vector Engine** | PostgreSQL 16 + `pgvector` (HNSW) | **Azure AI Search** (HNSW 3072-d) | **Vertex AI Vector Search** (ScaNN 1536-d) | **Mosaic AI Vector Search** (Delta Sync) |
| **Lexical Engine** | Full-Text Search (`tsvector`) | **Azure AI Search BM25** Engine | **BigQuery Text Search** / BM25 | **Databricks Full-Text Search** |
| **Re-Ranking** | Reciprocal Rank Fusion (RRF $k=60$) | **Bing Semantic Ranker** | **Vertex AI Ranking API** | **Mosaic AI Cross-Encoder Ranker** |
| **Access Control (RBAC)**| SQL GIN: `WHERE allowed_roles ?| $roles`| **OData Filter**: `allowed_roles/any(...)`| **Vertex Restricts**: `allowed_roles` | **filters_json**: `allowed_roles` (Unity Catalog) |
| **Embedding Generation** | OpenAI `text-embedding-3-large` | **Azure OpenAI** `text-embedding-3-large` | **Vertex AI / Gemini** `text-embedding-004` | **Databricks Serving** `bge-large-en` |
| **Chat Generation (LLM)** | OpenAI `gpt-4o` | **Azure OpenAI** `gpt-4o` Deployments | **Gemini 1.5 Pro / Flash** | **Databricks DBRX / Llama 3.1 70B** |
| **Distributed Tracing** | Jaeger All-In-One (Badger LSM) | **Azure Application Insights** | **Google Cloud Trace & Logging** | **Databricks MLflow System Tables** |

---

### 2. Cloud Resource Provisioning & Architectural Guardrails

#### 2.1. Microsoft Azure AI Provisioning
1. **Resource Group**: Create `rg-enterprise-rag-dev` (or `rg-enterprise-rag-prod`) in a region supporting model deployments (e.g., `East US 2` or `Sweden Central`).
2. **Azure OpenAI Service**: Create resource `oai-enterprise-rag` (**Standard S0**) and deploy **`text-embedding-3-large`** and **`gpt-4o`** in Azure AI Foundry.
3. **Azure AI Search**: Create service `search-enterprise-rag` on the **Standard** tier (required for **Bing Semantic Ranker** `semantic-config`) and enable the Semantic Ranker plan.
4. **Azure Application Insights**: Create `appi-enterprise-rag` and copy the `APPLICATIONINSIGHTS_CONNECTION_STRING`.

#### 2.2. Google Cloud (Vertex AI Vector Search) Provisioning
1. **Create Index & Endpoint**:
   - In Google Cloud Console (**Vertex AI → Vector Search**), create an index with **1536 dimensions**, metric **COSINE**, and algorithm **Tree-AH (ScaNN)** with `STREAM_UPDATE`.
   - Deploy the index to a public **Index Endpoint** with restricts namespace `allowed_roles`:
   ```bash
   gcloud ai index-endpoints deploy-index 7285634525504208896 \
       --deployed-index-id="enterprise_rag_index" \
       --display-name="enterprise_rag_index" \
       --index="4259655380562345984" \
       --project="gen-lang-client-0795078481" \
       --region="us-central1"
   ```
2. **Critical Vertex AI REST API Guardrails**:
   - **Restricts Schema**: The REST API requires `"allowList"` (not `"allow"`) inside each restrict object under namespace `allowed_roles`.
   - **IndexDatapoint Schema**: `IndexDatapoint` only accepts `datapointId`, `featureVector`, `restricts`, and `crowdingTag`. Arbitrary text fields are rejected with `HTTP 400 Bad Request`.
   - **Data-Plane vs. Control-Plane**: `:findNeighbors` must be called against the public data-plane domain (`*.vdb.vertexai.goog`), not `*-aiplatform.googleapis.com`.
   - **Two-Tier Chunk Hydration**: [`scripts/migrate_pg_to_gcp.py`](file:///c:/src/enterprise-rag-pgvector-rbac/scripts/migrate_pg_to_gcp.py) exports [`app/db/gcp_chunks_cache.json`](file:///c:/src/enterprise-rag-pgvector-rbac/app/db/gcp_chunks_cache.json) for sub-millisecond (<1ms) local chunk hydration, with automatic fallback to PostgreSQL (`WHERE c.id::text = ANY($1::text[])`) for uncached chunks.

#### 2.3. Databricks (Mosaic AI Vector Search) Provisioning
1. **Unity Catalog Delta Table**: Create `main.enterprise_rag.document_chunks` with Change Data Feed enabled (`TBLPROPERTIES (delta.enableChangeDataFeed = true)`).
2. **Vector Search Endpoint & Index**: Create endpoint `enterprise_vs_endpoint` and index `main.enterprise_rag.document_chunks_index` (primary key `id`, dimension `1536`, filterable metadata column `allowed_roles`).

---

### 3. Multi-Cloud Environment Configuration (`.env`)

```ini
# ==============================================================================
# Multi-Cloud Switcher: 'pgvector', 'azure', 'gcp', 'databricks'
# ==============================================================================
RETRIEVAL_BACKEND="azure"         # or "gcp", "databricks", "pgvector"

# --- [Azure AI Search & Azure OpenAI] ---
AZURE_OPENAI_ENDPOINT="https://oai-enterprise-rag.openai.azure.com/"
AZURE_OPENAI_API_KEY="<your-azure-openai-key>"
AZURE_OPENAI_API_VERSION="2024-06-01"
AZURE_OPENAI_CHAT_DEPLOYMENT="gpt-4o"
AZURE_OPENAI_EMBEDDING_DEPLOYMENT="text-embedding-3-large"
AZURE_SEARCH_ENDPOINT="https://search-enterprise-rag.search.windows.net"
AZURE_SEARCH_API_KEY="<your-azure-search-key>"
AZURE_SEARCH_INDEX_NAME="enterprise-documents-index"
APPLICATIONINSIGHTS_CONNECTION_STRING="InstrumentationKey=...;IngestionEndpoint=..."

# --- [Google Cloud Vertex AI Vector Search] ---
GCP_PROJECT_ID="gen-lang-client-0795078481"
GCP_REGION="us-central1"
GCP_INDEX_ENDPOINT_ID="7285634525504208896"
GCP_INDEX_ID="4259655380562345984"
GCP_DEPLOYED_INDEX_ID="enterprise_rag_index"
GCP_INDEX_ENDPOINT_DOMAIN="1876216656.us-central1-226714713434.vdb.vertexai.goog"
GCP_VECTOR_STORE="vertex_ai"

# --- [Databricks Mosaic AI Vector Search] ---
DATABRICKS_HOST="dbc-xxxx.cloud.databricks.com"
DATABRICKS_TOKEN="dapi_xxxxxxxxxxxxxxxx"
DATABRICKS_VECTOR_SEARCH_ENDPOINT_NAME="enterprise_vs_endpoint"
DATABRICKS_INDEX_NAME="main.enterprise_rag.document_chunks_index"
```

---

### 4. Automated Migration & Unified Execution

```powershell
# 1. Provision target cloud indexes
python scripts/setup_azure_search.py               # Azure AI Search index
python scripts/setup_gcp_vector_search.py          # Google Cloud Vertex AI / BigQuery
python scripts/setup_databricks_vector_search.py   # Databricks Unity Catalog index

# 2. Execute Batch Data Migration from PostgreSQL
python scripts/migrate_pg_to_azure.py              # Extract & upload to Azure
python scripts/migrate_pg_to_gcp.py                # Extract & upload to Google Cloud
python scripts/migrate_pg_to_databricks.py         # Extract & upload to Databricks

# 3. Or Run Unified Multi-Cloud Orchestrator
python scripts/migrate_multicloud.py --target all  # Migrates to all clouds

# 4. Run automated test suites
python -m pytest tests/test_azure_search.py -v
python -m pytest tests/test_multicloud_search.py -v
```

---

### 5. Zero-Trust RBAC Implementations Across All 4 Backends

#### PostgreSQL In-Database RBAC ([`app/db/manager.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/db/manager.py))
```sql
SELECT d.document_id, d.title, c.chunk_index, c.content, d.allowed_roles, 
       1 - (c.embedding <=> $1::vector) AS similarity
FROM document_chunks c
JOIN documents d ON c.document_id = d.id
WHERE d.allowed_roles ?| $2::text[]
ORDER BY c.embedding <=> $1::vector
LIMIT $3;
```

#### Azure AI Search OData Collection RBAC ([`app/db/azure_search.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/db/azure_search.py))
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

#### Google Cloud Vertex AI Restricts RBAC ([`app/db/gcp_search.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/db/gcp_search.py))
```python
restricts = [{"namespace": "allowed_roles", "allowList": sanitized_roles}]
results = await client.find_neighbors(
    query_vector=query_vector,
    restricts=restricts,
    limit=limit,
)
```

#### Databricks Mosaic AI Unity Catalog RBAC ([`app/db/databricks_search.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/db/databricks_search.py))
```python
filters_dict = {"OR": [{"allowed_roles": role} for role in sanitized_roles]}
results = await client.query_index(
    query_vector=query_vector,
    filters_json=json.dumps(filters_dict),
    limit=limit,
)
```

**Zero-Trust Guarantee**: Across all four implementations, if a caller presents no verified roles (`user_roles = []`), the query engine short-circuits immediately and returns `[]` without querying disk or network.

---

### 6. Solved Multi-Cloud Engineering Pitfalls & Root Cause Analysis

1. **Azure OpenAI Streaming `IndexError: list index out of range`**:
   - **Root Cause**: Azure OpenAI emits trailing metadata/filter chunks with empty `chunk.choices = []`. Unconditional indexing `chunk.choices[0]` threw an uncaught exception.
   - **Resolution**: Added `if not chunk.choices: continue` guards across all streaming generators in [`app/db/llm.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/db/llm.py).
2. **FastMCP Server `[WinError 1225]` Connection Refused**:
   - **Root Cause**: FastMCP tool `search_sdlc_context` was hardcoded to local PostgreSQL (`127.0.0.1:5432`). When transitioning to cloud backends, local PostgreSQL was offline.
   - **Resolution**: Integrated the Multi-Cloud router in [`app/mcp/gateway.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/mcp/gateway.py) so FastMCP tools route dynamically to `azure`, `gcp`, `databricks`, or `pgvector` based on `RETRIEVAL_BACKEND`.
3. **`python-dotenv` Syntax Parsing Warnings**:
   - **Root Cause**: Trailing comments without whitespace and unquoted multi-line private keys in `.env`.
   - **Resolution**: Standardized key-value pairs with clean quoting.

---

## Disclaimer & Synthetic Data Security Notice

> [!CAUTION]
> **Data Security & Synthetic Assets**:
> * All test documents, corporate financial summaries, and account figures referenced within this repository and test suite are **synthetic mock assets** generated solely for technical evaluation of Role-Based Access Control (RBAC) and vector similarity search.
> * None of the indexed texts contain genuine Personally Identifiable Information (PII) or authentic material financial records.
> * Always ensure telemetry scrubbers are enabled in enterprise production environments to redact sensitive tokens, authorization headers, and restricted document fragments prior to exporting spans to centralized tracing collectors.