# 🛡️ Enterprise Zero-Trust RAG & Autonomous SDLC
> **Architect:** **[Ken Wong](https://www.linkedin.com/in/kenwong-architect/)** — An enterprise-grade, shift-left reference implementation combining **In-Database Zero-Trust Vector RBAC** with an **Autonomous Self-Healing SDLC Agent**.  
> **Tech Stack:** PostgreSQL 16 + pgvector, FastAPI, Streamlit, Google OAuth 2.0 PKCE, Google JWKS, FastMCP, LangGraph.
| Live Artifact | Description | Access Link |
| :--- | :--- | :--- |
| **Interactive UI** | Shift-Left In-Database RBAC & Session Monitor | [enterprise-rag-pgvector-rbac.streamlit.app](https://enterprise-rag-pgvector-rbac.streamlit.app) |
| **API Docs** | Live OpenAPI / Interactive Swagger UI | [enterprise-rag-api-ksez.onrender.com/docs](https://enterprise-rag-api-ksez.onrender.com/docs) |
| **Source Code** | Auditable Source Repository & Offline Test Suite | [github.com/Kenono2000/enterprise-rag-pgvector-rbac](https://github.com/Kenono2000/enterprise-rag-pgvector-rbac) |
**Quick Navigation:** [1. Why In-DB RBAC?](#1-the-core-value-why-in-database-rbac) · [2. Executive Summary](#2-executive-summary-the-9-core-engineering-patterns) · [3. Architecture & Blueprints](#3-system-architecture--visual-blueprints) · [4. Quickstart](#4-5-minute-quickstart) · [5. 8 Engineering Layers](#5-architectural-deep-dive-the-8-engineering-layers) ([L1: DB](#layer-1-database--pgvector-rbac-schemasql--appdb) · [L2: Auth](#layer-2-identity-tokens--session-security-appauth) · [L3: Ingest](#layer-3-high-performance-ingestion-pipeline-scriptsingestpy--libsutilitiespy) · [L4: Hybrid RAG](#layer-4-rag-quality-hybrid-search--grounding-guardrails) · [L5: FastAPI/UI](#layer-5-fastapi-backend--streamlit-streaming-frontend) · [L6: OTel](#layer-6-observability-distributed-tracing--container-hardening) · [L7: FastMCP](#layer-7-fastmcp-agent-gateway-appmcp) · [L8: SDLC Agent](#layer-8-autonomous-self-healing-sdlc-agent-agent)) · [6. Multi-Cloud](#6-multi-cloud-migration-playbook--architecture-azure-gcp-databricks) · [7. Threat Model & Pitfalls](#7-threat-model--solved-engineering-pitfalls) · [8. Runbook](#8-incident-response-operational-runbook--jaeger-persistence-verification) · [9. Tests (120)](#9-testing--verification-guide-120-tests-119-passed-1-skipped) · [10. Code Reference](#10-codebase-organization-configuration--code-reference) · [11. Disclaimer](#11-disclaimer--synthetic-data-security-notice)

## 1. The Core Value: Why In-Database RBAC?
Traditional enterprise RAG architectures filter permissions **after** vector retrieval in Python memory (*Post-Filtering*), creating two critical production flaws:
```text
❌ Standard Post-Filtering (Memory Leaks & Recall Starvation):
[Query] ──► [Vector DB: Top-K] ──► [Python App Filters by Role] ──► [LLM Context] (Context Eviction & Memory Leaks)
✅ Zero-Trust In-Database RBAC (Shift-Left Security):
[Query] ──► [Verified JWT] ──► [PostgreSQL: GIN Filter + HNSW Scan] ──► [LLM Context] (Unauthorized data never leaves DB disk)
```
1. **Eliminates Recall Starvation**: When top-$K$ vector matches belong to restricted roles, post-filtering drops them in application memory—returning **0 results** to the user even when authorized documents exist in the database.
2. **Zero Memory Leaks**: In-database RBAC evaluates `WHERE d.allowed_roles ?| $2::text[]` via a **GIN Index** *before* scanning the **HNSW Vector Index**. Unauthorized rows never leave database disk, never cross TLS, and never enter application RAM.

## 2. Executive Summary: The 9 Core Engineering Patterns
| # | Architectural Layer | Key Engineering Pattern | Primary Business & Security Outcome |
| :-: | :--- | :--- | :--- |
| **1** | **Vector Database** | **Pre-Filtered GIN + HNSW RBAC** & 1536-d Matryoshka truncation | Zero recall starvation, zero memory leaks, **50% RAM savings** (>98% recall). |
| **2** | **Identity & Auth** | **Stateless OAuth 2.0 PKCE**, HMAC state & encrypted cookie rehydration | Survives F5 reloads & multi-worker scale-out with **zero Redis**; SOC-2 15m/12h bounds. |
| **3** | **Ingestion Pipeline** | **64KB Streaming SHA-256 De-duplication** & token-aligned splitting | $O(1)$ skip for unchanged files; preserves Markdown tables; `tenacity` 429 backoff. |
| **4** | **RAG Quality** | **Dense + Sparse Hybrid Search (RRF $k=60$)** & `GroundingGuardrail` | Captures semantic intent + exact SKUs/error codes; regex-verified citations. |
| **5** | **Async Runtime** | **Event-Loop-Scoped Pools**, `SKIP LOCKED` outbox & `/readyz` probes | Eliminates `RuntimeError: Event loop is closed`; durable worker queue; K8s ready. |
| **6** | **Observability** | **Full-Stack OpenTelemetry** (Jaeger Badger LSM + Azure Monitor) | End-to-end spans across UI, FastAPI, MCP & LLM; persistent 7-day trace storage. |
| **7** | **Agent Gateway** | **Zero-Trust FastMCP** (`extra='forbid'`, rate limiter & token breaker) | Enforces JWT + DB RBAC, 60 req/min sliding window & 8K/50K token circuit breakers. |
| **8** | **Autonomous SDLC** | **Tiered Subagent Routing (`inherit`/`flash`/`pro`)** & **AST `PolicyEngine`** | Offloads log triage to Gemini Flash (`test-triager`) & diff audit to Gemini Pro (`cross-model-judge`). |
| **9** | **Multi-Cloud** | **Quad-Mode Strategy Pattern** (`pgvector`, `azure`, `gcp`, `databricks`) | Zero-downtime `.env` switching with native pre-filtering across all 4 cloud engines. |
### Key Architectural Talking Points
1. **Shift-Left In-Database Zero-Trust Vector RBAC**: Normalized 2-table DDL (`documents` + `document_chunks` with `ON DELETE CASCADE`), parameterized `$2::text[]` SQL injection immunity, empty-role short-circuiting (`return []`), and deterministic offline mock vectors (`[0.01 * (i % 5) for i in range(1536)]`).
2. **Stateless OAuth 2.0 PKCE & JWKS**: RFC 7636 `S256` code challenge, HMAC-SHA256 signed `state` (300s TTL), `zlib`-compressed HMAC session cookie (`enterprise_rag_session`) for silent OAuth token rotation on F5 refresh, and multi-IdP JWKS verification (`leeway=60s`) across Google, Azure AD, Okta, Cognito, and Keycloak.
3. **Idempotent Ingestion**: B-Tree hash index (`idx_documents_file_hash`) detects file changes in 64KB blocks, purges stale chunks on update, splits on Markdown boundaries (`800` tokens, `100` overlap), and batches embeddings (`64` chunks/batch) with exponential backoff.
4. **Hybrid Search, RRF & Anti-Hallucination**: Combines HNSW cosine similarity (`1 - <=>`) with GIN full-text search (`ts_rank`) via Reciprocal Rank Fusion, re-ranks via Cross-Encoder (or 50/35/15 weighted heuristic fallback), and enforces `[Doc: <Title>, Chunk <Index>]` citations or explicit refusal.
5. **High-Concurrency Async FastAPI & Transactional Outbox**: Scopes `asyncpg` pools and `AsyncOpenAI` clients by `asyncio.get_running_loop()`, implements PostgreSQL transactional outbox queuing (`sdlc_outbox_events`) with `FOR UPDATE SKIP LOCKED` row-level worker locking, and verifies `pg_extension WHERE extname = 'vector'` on `/readyz`.
6. **OpenTelemetry & Hardened Containers**: Exports OTLP gRPC (`:4317`) to Jaeger (Badger LSM disk persistence) and Azure App Insights, retains a 1,000-event ring buffer at `/api/v1/metrics/observability`, validates config at boot via `Pydantic BaseSettings`, and runs Docker as non-root UID `10001`.
7. **Sovereign FastMCP Gateway & Blast-Radius Controls**: Exposes `search_sdlc_context` and `propose_patch` tools with strict Pydantic `ConfigDict(extra="forbid")` schemas (`MCPSearchRequest`, `MCPPatchRequest`), per-caller `SlidingWindowRateLimiter` (60 req/60s), active `TokenCircuitBreaker` (`8,000` req / `50,000` issue tokens), and caller-attribution audit spans.
8. **Self-Healing LangGraph SDLC Agent & Tiered Model Subagents**: Pairs frontier reasoning models (`model: inherit`) with specialized subagents in `.agent/agents/*.md`—delegating high-speed `pytest` failure classification (`compilation_error`, `assertion_failure`, `timeout`) and context compaction (`compact_agent_context`) to `test-triager` (`model: flash`) and independent pre-PR diff verification + rubric scoring to `cross-model-judge` (`model: pro`).
9. **Quad-Mode Multi-Cloud Vector Strategy**: Translates pre-filtered RBAC across PostgreSQL (`?|`), Azure AI Search (OData `allowed_roles/any(...)`), GCP Vertex AI (`restricts` `allowList` + <1ms local JSON cache hydration), and Databricks Mosaic AI (`filters_json`).

## 3. System Architecture & Visual Blueprints
### High-Level 4-Stage Architectural Flow
```mermaid
%%{init: {'flowchart': {'nodeSpacing': 15, 'rankSpacing': 25, 'padding': 8}}}%%
flowchart LR
    subgraph IdentityLayer ["1. Identity & Auth"]
        direction TB
        AuthCode["OAuth 2.0 PKCE<br/>(Google Cloud)"] --> JWKSValidator["JWKS Validator<br/>(RS256 Signature)"] --> RoleMapper["Role Extractor<br/>(Custom Claims)"]
    end
    subgraph RetrievalLayer ["2. Data & Search"]
        direction TB
        PGVector["PostgreSQL 16<br/>(GIN + HNSW Index)"] --> HybridRanker["Hybrid Ranker<br/>(RRF k=60 / BM25)"]
        CloudSearch["Cloud Vector Search<br/>(Azure / GCP / DBX)"] --> HybridRanker
    end
    subgraph ServiceLayer ["3. Gateways & UI"]
        direction TB
        APIGateway["FastAPI Gateway<br/>(Async Stream SSE)"] --> StreamlitUI["Streamlit UI<br/>(Inspector Mode)"]
        MCPGateway["FastMCP Server<br/>(Tool Sandbox)"] --> StreamlitUI
    end
    subgraph SDLCLayer ["4. Self-Healing Agent"]
        direction TB
        AgentPropose["LangGraph Engine<br/>(State Machine)"] --> ASTGuardrail["AST Auditor<br/>(Banned Syscalls)"] --> PytestRunner["Pytest Harness<br/>(Automated TDD)"]
    end
    IdentityLayer --> RetrievalLayer --> ServiceLayer --> SDLCLayer
    style IdentityLayer fill:#f8fafc,stroke:#94a3b8,stroke-width:1.5px
    style RetrievalLayer fill:#f0f9ff,stroke:#0284c7,stroke-width:1.5px
    style ServiceLayer fill:#fdf4ff,stroke:#c026d3,stroke-width:1.5px
    style SDLCLayer fill:#dcfce7,stroke:#22c55e,stroke-width:1.5px
```
### Detailed Multi-Cloud & Local System Topology
```mermaid
%%{init: {'flowchart': {'nodeSpacing': 15, 'rankSpacing': 25, 'padding': 8}}}%%
flowchart LR
    subgraph Clients ["1. Clients & Auth"]
        direction TB
        browser["Streamlit UI<br/>(Port :8501)"] --> google["Google OAuth 2.0<br/>(PKCE + JWKS)"] --> cookie["Session Cookie<br/>(15m Idle / 12h Max)"]
        mcp_client["AI Coding Agent<br/>(Claude / Cursor)"]
    end
    subgraph Gateways ["2. Core Gateways"]
        direction TB
        api["FastAPI Gateway<br/>(Port :8000)"] --> pool["AsyncPG Pool<br/>(Loop-Aware)"]
        mcp_gw["FastMCP Server<br/>(search_sdlc_context)"] --> pool
        agent["SDLC Agent<br/>(LangGraph + AST)"] --> api
    end
    subgraph LocalEnv ["3. Local Stack (pgvector)"]
        direction TB
        local_db["PostgreSQL 16<br/>• GIN Role Filter<br/>• HNSW 1536-d"]
        openai_api["OpenAI API<br/>• embedding-3-large<br/>• gpt-4o Chat"]
        jaeger["Jaeger Tracing<br/>• OTLP (:4317)<br/>• Badger LSM"]
    end
    subgraph CloudEnv ["4. Managed Cloud Backends"]
        direction TB
        azure_env["Microsoft Azure<br/>• AI Search (OData)<br/>• Azure OpenAI<br/>• App Insights"]
        gcp_env["Google Cloud<br/>• Vertex Vector<br/>• Restricts Filter<br/>• Gemini 1.5 Pro"]
        dbx_env["Databricks<br/>• Mosaic Vector<br/>• Unity Catalog<br/>• Llama 3.1 70B"]
    end
    Clients --> Gateways
    Gateways -->|pgvector| LocalEnv
    Gateways -->|azure / gcp / dbx| CloudEnv
    style Clients fill:#fefce8,stroke:#ca8a04,stroke-width:1.5px
    style Gateways fill:#f0fdf4,stroke:#16a34a,stroke-width:1.5px
    style LocalEnv fill:#f0f9ff,stroke:#0284c7,stroke-width:1.5px
    style CloudEnv fill:#fdf4ff,stroke:#c026d3,stroke-width:1.5px
    style local_db fill:#e0f2fe,stroke:#0369a1,stroke-width:1.5px
    style azure_env fill:#fae8ff,stroke:#a21caf,stroke-width:1.5px
    style gcp_env fill:#fee2e2,stroke:#b91c1c,stroke-width:1.5px
    style dbx_env fill:#ffedd5,stroke:#c2410c,stroke-width:1.5px
```

## 4. 5-Minute Quickstart
```powershell
git clone https://github.com/Kenono2000/enterprise-rag-pgvector-rbac.git && cd enterprise-rag-pgvector-rbac
python -m venv .venv && .\.venv\Scripts\Activate.ps1 && python -m pip install -r requirements.txt
python -m pytest -v                                                     # 1. Run 100% offline test suite (120 tests)
docker compose up -d && psql -U postgres -d enterprise_rag -f schema.sql # 2. Start PG16 + pgvector & Jaeger Badger
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload       # 3. Launch FastAPI Backend (:8000)
python -m streamlit run streamlit_app.py --server.port 8501              # 4. Launch Streamlit UI (:8501)
python -m app.mcp                                                        # 5. Launch FastMCP Gateway (stdio/SSE)
```
* **Local Endpoints**: Streamlit UI (`http://localhost:8501`) · Swagger Docs (`http://localhost:8000/docs`) · Probes (`/healthz`, `/readyz`) · Telemetry (`/api/v1/metrics/observability`) · Jaeger UI (`http://localhost:16686`).

## 5. Architectural Deep Dive: The 8 Engineering Layers
### Layer 1: Database & pgvector RBAC (`schema.sql` & `app/db/`)
```sql
SELECT d.document_id, d.title, c.chunk_index, c.content, d.allowed_roles,
       1 - (c.embedding <=> $1::vector) AS similarity
FROM document_chunks c JOIN documents d ON c.document_id = d.id
WHERE d.allowed_roles ?| $2::text[]
  AND (c.embedding_model = 'text-embedding-3-large' OR c.embedding_model IS NULL)
ORDER BY c.embedding <=> $1::vector LIMIT $3;
```
* **`?|` (JSONB Exists-Any)**: Evaluates role membership via the **GIN index** (`idx_documents_allowed_roles_gin`) *before* computing cosine distance (`<=>`) on the **HNSW index** (`m=16, ef_construction=64`).
* **Key Invariants**: (1) **SQL Injection Immunity** via parameterized `$2::text[]` array binding; (2) **Zero-Trust Short-Circuit** returning `[]` immediately when `user_roles` is empty; (3) **Matryoshka 1536-d Truncation** (`3072` ➔ `1536` dims, **50% RAM savings**, **>98% recall**); (4) **Loop-Aware Connection Pooling** (`DatabaseManager.get_pool()`) bound to active event loops; (5) **Normalized 2-Table DDL** (`documents` + `document_chunks` with `ON DELETE CASCADE`; see [Section 10.3](#103-postgresql-16--pgvector-ddl-reference-schemasql)).
### Layer 2: Identity, Tokens & Session Security (`app/auth/`)
```mermaid
%%{init: {'sequence': {'actorMargin': 30, 'boxMargin': 6, 'messageMargin': 22}}}%%
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
* **Stateless HMAC-Signed OAuth State**: `encode_pkce_state(verifier)` signs `{b64_payload}.{sig}` (300s TTL) with HMAC-SHA256—surviving redirects and multi-worker restarts with **zero Redis/DB state**.
* **F5 Reload Resilience**: Compresses (`zlib`), base64url-encodes, and HMAC-signs session data into `enterprise_rag_session`, rehydrating `st.session_state` and silently rotating expired ID tokens via `_refresh_id_token_sync()`.
* **Multi-IdP JWKS & Role Normalization**: Pre-validates issuers via `get_allowed_issuers()`, verifies RS256 signatures with `leeway=60s` clock-skew tolerance, and normalizes claims across `app_roles`, `roles`, `groups`, `cognito:groups`, and `realm_access.roles` against `KNOWN_ROLES`.
#### SOC-2 / HIPAA Session Lifecycle
```mermaid
%%{init: {'flowchart': {'nodeSpacing': 15, 'rankSpacing': 25, 'padding': 8}}}%%
flowchart LR
    Check["Session Event<br/>(Periodic Check)"] --> Idle{"Inactivity<br/>> 15 min?"}
    Idle -->|Yes| Terminate["Terminate Session<br/>(Wipe Cookie & Login)"]
    Idle -->|No| Ceiling{"Total Session<br/>> 12 hours?"}
    Ceiling -->|Yes| Terminate
    Ceiling -->|No| Refresh["Silent Token Refresh<br/>(via Google /token)"] --> OK["Session Active<br/>& Protected"]
    style Terminate fill:#fee2e2,stroke:#ef4444,stroke-width:1.5px
    style OK fill:#dcfce7,stroke:#22c55e,stroke-width:1.5px
    style Check fill:#f3e8ff,stroke:#a855f7,stroke-width:1.5px
```
| Token / Policy | Lifetime | Enforcement Mechanism |
| :--- | :--- | :--- |
| **ID / Access Token** | 15–60 min | In-memory session state; verified via cached JWKS public certs (`leeway=60s`). |
| **Refresh Token** | 30 days | `HttpOnly` encrypted cookie (`enterprise_rag_session`) for silent rotation. |
| **Sliding Idle Timeout** | **15 min** | DOM activity listeners (`mousedown`, `keydown`, `scroll`) wipe cookie on inactivity. |
| **Hard Session Ceiling** | **12 hours** | Forces full re-authentication regardless of continuous activity. |
### Layer 3: High-Performance Ingestion Pipeline (`scripts/ingest.py` & `libs/utilities.py`)
```mermaid
%%{init: {'flowchart': {'nodeSpacing': 15, 'rankSpacing': 25, 'padding': 8}}}%%
flowchart LR
    subgraph Stage1 ["1. Intake & Change Detection"]
        direction TB
        Raw["Raw Documents<br/>(PDF, MD, DOCX)"] --> Hash["SHA-256 Hashing<br/>(64KB Blocks)"] --> Check{"Exists in DB<br/>Same Hash?"}
        Check -->|Yes| Skip["Skip Content<br/>(Zero Overhead)"]
    end
    subgraph Stage2 ["2. Chunking & Embedding"]
        direction TB
        Split["Semantic Split<br/>(512-800 Tokens)"] --> Meta["Attach Metadata<br/>(doc_id, index)"] --> Embed["Batch Embed<br/>(Tenacity Retry)"]
    end
    subgraph Stage3 ["3. Dual Persistence"]
        direction TB
        Master["Upsert Master &<br/>Purge Stale Chunks"] --> PG["PostgreSQL 16<br/>(HNSW + GIN)"]
        Master -.->|Sync| Azure["Azure AI Search<br/>(OData RBAC + HNSW)"]
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
* **64KB Streaming SHA-256 De-duplication**: `compute_file_hash()` checks `idx_documents_file_hash` in $O(1)$ time—skipping unchanged files with zero API calls and automatically purging stale chunks when a file is modified (override with `--force`).
* **Structure-Preserving Token Chunking**: `RecursiveCharacterTextSplitter.from_tiktoken_encoder` (`chunk_size=800`, `chunk_overlap=100`) splits along Markdown headers (`\n## `, `\n### `) and table pipes (`\n|`) so tables remain intact.
* **Resilient Batch Embedding**: Slices chunks into 64-item batches wrapped with `tenacity` exponential backoff (`2s`–`60s`, 5 attempts) to survive HTTP `429`/`503` rate limits.
### Layer 4: RAG Quality, Hybrid Search & Grounding Guardrails
```text
Dense Retrieval (HNSW Vector Index):  [Semantic Intent] ──► Cosine Similarity (1 - <=>) ─┬─► RRF (k=60) ──► Cross-Encoder Re-Rank
Sparse Retrieval (GIN tsvector Index): [Exact SKUs/IDs] ──► Lexical Rank (ts_rank)      ─┘
```
* **Reciprocal Rank Fusion (RRF)**: Combines dense semantic rank and sparse keyword rank (`ERR-502`, `FIN-2026-001`)—both pre-filtered by `d.allowed_roles ?| $user_roles::text[]`—using smoothing constant $k = 60$: $RRF(d) = \sum_{m \in \{\text{dense}, \text{sparse}\}} \frac{1}{60 + rank_m(d)}$.
* **Two-Stage Cross-Encoder Re-Ranking**: `rerank_candidates()` scores top RRF candidates via `CrossEncoder` / Cohere Rerank (with a deterministic offline fallback: **50%** semantic + **35%** lexical intersection + **15%** RRF score).
* **Anti-Hallucination `GroundingGuardrail`**: Requires every claim to cite `[Doc: <Title>, Chunk <Index>]`, verifies cited titles against retrieved chunks via regex, and enforces explicit refusal (*"I do not have sufficient information..."*) when context is insufficient.
### Layer 5: FastAPI Backend & Streamlit Streaming Frontend
* **Kubernetes Health Probes (`app/main.py`)**: `GET /healthz` (immediate process liveness), `GET /readyz` (verifies active `asyncpg` pool acquisition and `pgvector` extension installation; returns `HTTP 503` on failure), and `POST /api/v1/query` (pre-filtered hybrid RAG, RRF fusion, grounding validation, and OTel span recording).
* **Real-Time SSE Token Streaming & Concurrency (`streamlit_app.py`)**: Streams tokens via `st.write_stream` (`chat_completion_stream`) with expandable SQL & citation inspectors; prevents connection exhaustion via `@st.cache_resource` (`get_shared_db_pool()`) and avoids nested loop crashes via `run_async` (`nest_asyncio` + isolated `ThreadPoolExecutor`).
### Layer 6: Observability, Distributed Tracing & Container Hardening
```mermaid
%%{init: {'flowchart': {'nodeSpacing': 15, 'rankSpacing': 25, 'padding': 8}}}%%
flowchart LR
    subgraph Sources ["1. Trace Producers"]
        direction TB
        Browser["User Browser<br/>(Client Session)"] -->|chat_interaction| UI["Streamlit UI<br/>(Port :8501)"]
        UI -->|http_request| API["FastAPI Gateway<br/>(Port :8000)"]
        UI -->|mcp_tool| MCP["FastMCP Server<br/>(app/mcp)"]
        API -->|rag.generate| LLM["LLM Service<br/>(OpenAI / Azure)"]
    end
    subgraph Core ["2. Telemetry Engine"]
        direction TB
        OTel["OpenTelemetry SDK<br/>(observability.py)<br/>• BatchSpanProcessor<br/>• Semantic RAG Tags"]
    end
    subgraph Sinks ["3. Tracing Backends"]
        direction TB
        Jaeger["Jaeger All-In-One<br/>• OTLP gRPC (:4317)<br/>• Badger LSM Store<br/>• Web UI (:16686)"]
        AppInsights["Azure App Insights<br/>• Azure Monitor<br/>• Cloud Dashboard"]
    end
    Sources -->|OTLP Spans| Core
    Core -->|Local Jaeger| Jaeger
    Core -->|Azure Monitor| AppInsights
    style Sources fill:#f8fafc,stroke:#94a3b8,stroke-width:1.5px
    style Core fill:#f0fdf4,stroke:#16a34a,stroke-width:1.5px
    style Sinks fill:#f0f9ff,stroke:#0284c7,stroke-width:1.5px
    style Jaeger fill:#fefce8,stroke:#ca8a04,stroke-width:1.5px
    style AppInsights fill:#fdf4ff,stroke:#c026d3,stroke-width:1.5px
```
* **End-to-End Span Attributes**: Tracks `user.id`, `user.role`, `rag.question`, `rag.source_count`, `rag.processing_time_ms`, and `mcp.tool_name` across OTLP gRPC (`:4317`), backed by a 1,000-event ring buffer (`GET /api/v1/metrics/observability`).
* **Persistent Jaeger Badger LSM Storage**: Configured with `SPAN_STORAGE_TYPE=badger`, `user: "0:0"` volume permission hardening, and a 7-day TTL (`168h`) so traces survive container restarts (see [Section 10.4](#104-container--observability-configuration-reference)).
* **Hardened Multi-Stage `Dockerfile` & Fail-Fast Config**: `Pydantic BaseSettings` (`app/config.py`) validates environment variables at startup; production container strips `gcc`/`libpq-dev` and runs as non-root `appuser` (UID `10001`).
### Layer 7: FastMCP Agent Gateway (`app/mcp/`)
Standardizes Zero-Trust tool and resource access for external AI coding agents (Claude Desktop, Cursor, CLI agents) over `stdio` and `SSE` with `ConfigDict(extra="forbid")` schemas (`MCPSearchRequest`, `MCPPatchRequest`), `SlidingWindowRateLimiter`, and `TokenCircuitBreaker`:
| MCP Primitive | Signature | Zero-Trust & Blast-Radius Governance |
| :--- | :--- | :--- |
| **Tool** | `search_sdlc_context(question, auth_token, user_roles)` | Verifies caller JWT, enforces 60 req/min rate limit + 8K/50K token circuit breaker, and executes in-DB RBAC retrieval. |
| **Tool** | `propose_patch(branch_name, patch_content, auth_token)` | Authenticates submitter identity, enforces rate & token circuit breakers, and emits caller-attributed OTel audit spans. |
| **Resource** | `policy://sdlc-budget` | Publishes active token circuit breakers (`max_tokens_per_request=8,000`, `max_tokens_per_issue=50,000`), rate limits, and tool allowlists. |
### Layer 8: Autonomous Self-Healing SDLC Agent (`agent/`)
```mermaid
%%{init: {'flowchart': {'nodeSpacing': 15, 'rankSpacing': 25, 'padding': 8}}}%%
flowchart LR
    subgraph Intake ["1. Webhook & Init"]
        direction TB
        Hook["GitHub Webhook<br/>(HMAC Verified)"] --> Init["Initialize State<br/>& Git Branch"]
    end
    subgraph Gen ["2. Synthesis (inherit)"]
        direction TB
        Propose["Propose Patch<br/>(model: inherit)"] --> Apply["Apply Sandbox<br/>(Path Guard)"]
    end
    subgraph Audit ["3. Judge Gate (pro)"]
        direction TB
        Inspect["AST + Pro Judge<br/>(cross-model-judge)"] -->|Failed| Reject["Policy / Diff Fail<br/>(Blocked)"]
    end
    subgraph Verify ["4. Flash Triage Loop"]
        direction TB
        Test{"test-triager<br/>(model: flash)"} -->|Retry < 3| Repair["Repair Patch<br/>(Up to 3x Loop)"]
        Test -->|Retry >= 3| Escalate["Max Retries (3)<br/>(Escalate)"]
    end
    subgraph Done ["5. PR Delivery"]
        direction TB
        PR["Clean Git Commit<br/>& Open PR"]
    end
    Intake --> Gen --> Audit
    Audit -->|Passed| Verify
    Verify -->|Passed| Done
    style Intake fill:#f8fafc,stroke:#94a3b8,stroke-width:1.5px
    style Gen fill:#f0f9ff,stroke:#0284c7,stroke-width:1.5px
    style Audit fill:#fefce8,stroke:#ca8a04,stroke-width:1.5px
    style Verify fill:#fdf4ff,stroke:#c026d3,stroke-width:1.5px
    style Done fill:#f0fdf4,stroke:#16a34a,stroke-width:1.5px
    style Reject fill:#fee2e2,stroke:#ef4444,stroke-width:1.5px
    style Escalate fill:#fee2e2,stroke:#ef4444,stroke-width:1.5px
    style PR fill:#dcfce7,stroke:#22c55e,stroke-width:1.5px
```
* **LangGraph State Machine (`agent/workflow.py`)**: `initialize` (verifies `X-Hub-Signature-256` & creates `feature/AGENT-<id>` branch) ➔ `propose_patches` (`model: inherit`) ➔ `apply_patches` (blocks `..`, absolute paths, and `.git/`) ➔ `audit_patches` (`PolicyEngine` + `CrossModelJudgeSubagent` on `model: pro`) ➔ `run_tests` (`pytest` via `asyncio.to_thread` classified by `TestTriagerSubagent` on `model: flash`) ➔ `repair_patches` (injects structured Flash triage summary + trailing 2,500 chars of traceback, up to `max_attempts=3`) ➔ `finalize` (commits & opens PR).
* **Tiered Subagent Customization Pattern (`.agent/agents/*.md`)**:
  * [`arch-synthesizer.md`](file:///c:/src/enterprise-rag-pgvector-rbac/.agent/agents/arch-synthesizer.md) (`model: inherit`): Uses the primary session's frontier reasoning model for multi-file synthesis, RLS/HNSW invariant design, and complex patch generation.
  * [`test-triager.md`](file:///c:/src/enterprise-rag-pgvector-rbac/.agent/agents/test-triager.md) (`model: flash` / `TestTriagerSubagent`): Offloads high-volume mechanical test runs and classifies failures by root cause (`compilation_error`, `assertion_failure`, `timeout`) into a compact `TriageSummary`, eliminating frontier token burn on raw logs.
  * [`gemini-judge.md`](file:///c:/src/enterprise-rag-pgvector-rbac/.agent/agents/gemini-judge.md) (`name: cross-model-judge`, `model: pro` / `CrossModelJudgeSubagent`): Independent LLM-as-a-judge verifier that audits diffs against user requirements, regressions, missing edge cases, and security invariants, outputting a `PASS`/`FAIL` `JudgeVerdict` with exact `file:L<line>` references.
* **Pre-Execution AST, Secret & Schema Drift Guardrails (`agent/guardrails.py`)**: `ast.walk()` blocks `eval()`, `exec()`, and `__import__()` *before* test execution; compiled regex scanners block leaked keys (`sk-...`, `AIza...`, `-----BEGIN PRIVATE KEY-----`); `PolicyEngine.verify_schema_drift()` enforces `extra='forbid'` (`additionalProperties=False`) and prevents breaking contract drift.

## 6. Multi-Cloud Migration Playbook & Architecture (Azure, GCP, Databricks)
Switch runtime retrieval backends with zero downtime via `RETRIEVAL_BACKEND` (`pgvector` | `azure` | `gcp` | `databricks`):
```mermaid
%%{init: {'flowchart': {'nodeSpacing': 15, 'rankSpacing': 25, 'padding': 8}}}%%
flowchart LR
    subgraph Provisioning ["1. Cloud Provisioning"]
        direction TB
        Azure_P["Phase 1A:<br/>Azure AI Search<br/>(HNSW + Semantic)"]
        GCP_P["Phase 1B:<br/>Google Vertex AI<br/>(ScaNN Restricts)"]
        DBX_P["Phase 1C:<br/>Databricks Mosaic<br/>(Unity Catalog)"]
    end
    subgraph DataOps ["2. Data Pipeline"]
        direction TB
        MIG["Phase 2:<br/>Batch Migration<br/>(PostgreSQL Chunks)"] --> VAL["Phase 3:<br/>Index Validation<br/>(RBAC Pre-Filters)"]
    end
    subgraph Cutover ["3. Routing & Cutover"]
        direction TB
        ENV["Phase 4:<br/>Switch Backend<br/>(.env Toggle)"] --> TEST["Phase 5:<br/>Automated Tests<br/>(pytest Suite)"]
    end
    Provisioning --> DataOps --> Cutover
    style Provisioning fill:#f8fafc,stroke:#94a3b8,stroke-width:1.5px
    style DataOps fill:#f0f9ff,stroke:#0284c7,stroke-width:1.5px
    style Cutover fill:#dcfce7,stroke:#22c55e,stroke-width:1.5px
```
### Architectural Component Mapping Across Clouds
| Function | PostgreSQL (`pgvector`) | Microsoft Azure AI (`azure`) | Google Cloud (`gcp`) | Databricks (`databricks`) |
| :--- | :--- | :--- | :--- | :--- |
| **Vector Engine** | PostgreSQL 16 + `pgvector` (HNSW) | **Azure AI Search** (HNSW 3072-d) | **Vertex AI Vector Search** (ScaNN 1536-d) | **Mosaic AI Vector Search** (Delta Sync) |
| **Lexical / Re-Rank** | `tsvector` + RRF ($k=60$) | **BM25 + Bing Semantic Ranker** | **BigQuery BM25 + Vertex Ranking API** | **Full-Text + Mosaic Cross-Encoder** |
| **In-DB RBAC Filter** | `WHERE allowed_roles ?| $2::text[]` | OData: `allowed_roles/any(r: ...)` | ScaNN `restricts`: `allowList` | Unity Catalog: `filters_json` (`OR`) |
| **LLM & Embeddings** | OpenAI `gpt-4o` / `embedding-3-large` | **Azure OpenAI** `gpt-4o` | **Gemini 1.5 Pro** / `text-embedding-004` | **Llama 3.1 70B** / `bge-large-en` |
| **Observability** | Jaeger (Badger LSM-Tree) | **Azure Application Insights** | **Google Cloud Trace & Logging** | **Databricks MLflow System Tables** |
### Zero-Trust Pre-Filtering Code Across All 4 Backends
```python
# 1. PostgreSQL 16 + pgvector (app/db/manager.py)
WHERE d.allowed_roles ?| $2::text[] ORDER BY c.embedding <=> $1::vector LIMIT $3;
# 2. Microsoft Azure AI Search OData (app/db/azure_search.py)
role_filter = "allowed_roles/any(r: " + " or ".join([f"r eq '{r}'" for r in sanitized_roles]) + ")"
results = await client.search(search_text=query_text, vector_queries=[vq], filter=role_filter, top=limit)
# 3. Google Cloud Vertex AI Vector Search Restricts (app/db/gcp_search.py)
restricts = [{"namespace": "allowed_roles", "allowList": sanitized_roles}]
results = await client.find_neighbors(query_vector=query_vector, restricts=restricts, limit=limit)
# 4. Databricks Mosaic AI Unity Catalog (app/db/databricks_search.py)
filters_dict = {"OR": [{"allowed_roles": role} for role in sanitized_roles]}
results = await client.query_index(query_vector=query_vector, filters_json=json.dumps(filters_dict), limit=limit)
```
* **Cloud Provisioning Guardrails**: **Azure AI Search** (`search-enterprise-rag`, Standard tier, `semantic-config`, Azure OpenAI `gpt-4o` + `text-embedding-3-large`); **Google Cloud Vertex AI** (1536-d `COSINE` Tree-AH ScaNN on `*.vdb.vertexai.goog`, `"allowList"` restricts, and **<1ms** Two-Tier Chunk Hydration via `app/db/gcp_chunks_cache.json`); **Databricks Mosaic AI** (Unity Catalog `main.enterprise_rag.document_chunks` with `delta.enableChangeDataFeed = true`); **Unified CLI** (`python scripts/migrate_multicloud.py --target all`).

## 7. Threat Model & Solved Engineering Pitfalls
### Threat Model (STRIDE Matrix)
| Threat Category | Attack Vector | Platform Mitigation & Invariant |
| :--- | :--- | :--- |
| **Spoofing** | Forged JWT identity tokens | Cryptographic RS256 verification via cached JWKS public keys (`leeway=60s`) & issuer allowlist. |
| **Tampering** | In-flight payload manipulation | TLS 1.3, SHA-256 PKCE code challenges (`S256`), and HMAC-SHA256 state/cookie signing. |
| **Repudiation** | Unaudited data access | OpenTelemetry distributed tracing recording `user.id`, `user.role`, and cited sources on every span. |
| **Information Disclosure** | Vector DB memory snooping | **Shift-Left In-Database RBAC**: unauthorized vectors never leave disk or enter app RAM. |
| **Denial of Service** | Unbounded vector scans / loops | `asyncpg` connection pooling, `5000ms` query timeouts, HNSW indexing, and MCP token budgets. |
| **Elevation of Privilege** | Prompt injection / agent deputy | Roles extracted strictly from signed JWT claims validated against `KNOWN_ROLES`; AST `PolicyEngine`. |
### Solved Engineering Pitfalls & Root Cause Summary
| Symptom / Failure Mode | Root Cause | Permanent Engineering Fix |
| :--- | :--- | :--- |
| **Recall Starvation & Memory Leaks** | Post-filtering vector hits in Python drops restricted top-$K$ results. | **Pre-Filtered In-DB RBAC**: `WHERE allowed_roles ?| $2::text[]` via GIN index before HNSW scan. |
| **`RuntimeError: Event loop is closed`** | Global `AsyncOpenAI` & `asyncpg` pools retained closed Streamlit thread loops. | **Loop-Scoped Client Registry**: Keyed clients/pools by `asyncio.get_running_loop()` with auto-recycling. |
| **Streamlit Worker Loop Collisions** | Calling async coroutines inside active Streamlit worker loops failed. | **Thread-Safe Async Bridge (`run_async`)**: Applies `nest_asyncio` with `ThreadPoolExecutor` fallback. |
| **F5 Browser Reload Drops Login** | WebSocket reset wipes `st.session_state` in RAM; OAuth redirect loses state. | **Stateless HMAC State & Encrypted Cookie**: `enterprise_rag_session` rehydrates & rotates tokens silently. |
| **Sparse SKU / Error Code Misses** | Pure cosine similarity misses exact strings (`ERR-502`, `FIN-2026-001`). | **Hybrid Search + RRF ($k=60$)**: Merges HNSW vector rank + GIN `ts_rank` + Cross-Encoder re-ranking. |
| **LLM Hallucinations / False Refusals** | Unconstrained prompts invent facts; overly rigid prompts reject summaries. | **Calibrated `GroundingGuardrail`**: Enforces `[Doc: <Title>, Chunk <Index>]` regex validation + synthesis. |
| **Jaeger Badger `/badger/key: permission denied`** | Non-root Jaeger UID `10001` blocked from writing to root-owned Docker volume. | **Container Root Volume Mapping**: Set `user: "0:0"` with `SPAN_STORAGE_TYPE=badger` (`168h` TTL). |
| **Azure OpenAI Stream `IndexError`** | Azure emits trailing filter chunks with empty `chunk.choices = []`. | **Empty-Choice Guard**: Added `if not chunk.choices: continue` in all streaming generators (`app/db/llm.py`). |
| **FastMCP `[WinError 1225]` Refused** | MCP tool was hardcoded to local PostgreSQL (`:5432`) during cloud mode. | **Dynamic Multi-Cloud Router**: Wired `app/mcp/gateway.py` to dispatch via `RETRIEVAL_BACKEND`. |
| **`ImmatureSignatureError` (`iat`)** | Local NTP clock drift vs. Google OAuth token issuance servers. | **RFC 7519 Clock Skew Tolerance**: Configured `leeway=60` in `jwt.decode()`. |

## 8. Incident Response, Operational Runbook & Jaeger Persistence Verification
```mermaid
%%{init: {'flowchart': {'nodeSpacing': 15, 'rankSpacing': 25, 'padding': 8}}}%%
flowchart LR
    subgraph Detection ["1. Detection"]
        direction TB
        Alert["Alert Triggered<br/>(OTel / AppInsights)"] --> Trace["Trace Analysis<br/>(Inspect Traceparent)"]
    end
    subgraph Triage ["2. Triage"]
        direction TB
        ErrorClass{"Error Type?"} --> DBErr["Database / Latency"]
        ErrorClass --> AuthErr["Authentication Fail"]
    end
    subgraph Remediation ["3. Remediation"]
        direction TB
        DBErr --> Action1["Switch Backend<br/>(RETRIEVAL_BACKEND)"]
        AuthErr --> Action2["Rotate JWKS Cache<br/>(Flush Memory Lock)"]
    end
    Detection --> Triage --> Remediation
    style Detection fill:#f8fafc,stroke:#94a3b8,stroke-width:1.5px
    style Triage fill:#fef3c7,stroke:#d97706,stroke-width:1.5px
    style Remediation fill:#dcfce7,stroke:#22c55e,stroke-width:1.5px
```
* **Scenario A — Database Outage / Latency Failover**: Inspect spans in Jaeger (`http://localhost:16686`), switch `RETRIEVAL_BACKEND="azure"` (or `"gcp"` / `"databricks"`) in `.env`, and reload FastAPI (`uvicorn app.main:app --port 8000 --reload`).
* **Scenario B — JWKS Key Rotation Failure**: Verify `https://www.googleapis.com/oauth2/v3/certs`, restart the auth worker to flush `JWKSClient._cache`, and run `python -m pytest tests/test_auth.py -k "test_jwks" -v`.
* **Verifying Persistent Jaeger Traces**: Submit a query on `:8501`, inspect `chat_interaction` tags (`rag.question`, `rag.response`) at `http://localhost:16686`, run `docker compose restart jaeger`, and refresh—all traces remain intact on disk via Badger LSM storage.

## 9. Testing & Verification Guide (120 Tests: 119 Passed, 1 Skipped)
Run the complete test suite **100% offline** in ~41s via `python -m pytest -v`:
| Test Module | Tests | Key Invariants Verified |
| :--- | :---: | :--- |
| **`tests/test_auth.py`** | 34 | PKCE `S256`, stateless HMAC state (300s TTL), JWKS `leeway=60s`, multi-IdP claims, encrypted session cookies. |
| **`tests/test_mcp_auth.py`** | 14 | FastMCP JWT enforcement, `extra='forbid'` schemas, sliding-window rate limiter, token circuit breaker, `stdio` & `SSE`. |
| **`tests/test_agent.py`** | 10 | Webhook HMAC-SHA256, AST `eval`/`exec` blocking, schema drift detection, prefix caching, Flash `test-triager`, Pro `cross-model-judge`. |
| **`tests/test_ingest.py`** | 9 | 64KB SHA-256 de-duplication, modified file re-indexing, `--force` override, chunk prefix & stem matching. |
| **`tests/test_multicloud_search.py`** | 8 | GCP Vertex AI `restricts` (`allowList`), Databricks `filters_json`, dynamic backend routing, empty-role short-circuit. |
| **`tests/test_database_schema.py`** | 7 | Normalized DDL (`documents`, `document_chunks`, `sdlc_outbox_events`), `FOR UPDATE SKIP LOCKED` outbox queue, HNSW/GIN indexes. |
| **`tests/test_observability_and_health.py`** | 7 | `/healthz`, `/readyz` (503 on DB failure), `/api/v1/metrics/observability`, `BaseSettings`, SSE token streaming. |
| **`tests/test_utilities.py`** | 7 | `.pdf`/`.md`/`.docx` loaders, Tiktoken chunk splitting, metadata attribution, `tenacity` 429 retry backoff. |
| **`tests/test_hybrid_search.py`** | 6 | Reciprocal Rank Fusion ($k=60$), Cross-Encoder & fallback re-ranking, `GroundingGuardrail` citation verification. |
| **`tests/test_rag.py`** | 6 | FastAPI `/api/v1/query` 401 rejection, `422` on extra fields (`extra='forbid'`), `429` token circuit breaker, RBAC retrieval. |
| **`tests/test_security_rbac.py`** | 5 | SQL injection immunity, parameterized `$2::text[]` array binding, empty-role short-circuit, header sanitization. |
| **`tests/test_azure_search.py`** | 3 | OData `allowed_roles/any(...)` filter syntax, empty-role short-circuit, `RETRIEVAL_BACKEND="azure"` routing. |
| **`tests/test_integration_pgvector.py`** | 2 | Testcontainers `pgvector/pgvector:pg16` live container harness (1 skipped when Docker daemon is offline). |
| **Total** | **120** | **119 Passed, 1 Skipped (100% Offline Capable)** |

## 10. Codebase Organization, Configuration & Code Reference
### 10.1. Directory Structure
```text
enterprise-rag-pgvector-rbac/
├── app/                        # 🛡️ Zero-Trust RAG Microservice
│   ├── auth/                   # Identity: PKCE (pkce.py), JWKS (jwks.py), role mapper (role_mapper.py)
│   ├── db/                     # Data & AI: PostgreSQL (manager.py), Azure (azure_search.py), GCP (gcp_search.py), Databricks (databricks_search.py), LLM (llm.py)
│   ├── mcp/                    # FastMCP tools & policy resources (gateway.py)
│   ├── observability.py        # OpenTelemetry tracer, Jaeger Badger LSM & Azure Monitor exporters
│   ├── config.py               # Pydantic BaseSettings startup validation
│   └── main.py                 # FastAPI REST API (/api/v1/query, /healthz, /readyz, /webhooks/github)
├── agent/                      # 🤖 Autonomous Self-Healing SDLC Agent (workflow.py, guardrails.py, parser.py)
├── .agent/agents/              # ⚡ Antigravity Tiered Subagents (test-triager.md, gemini-judge.md, arch-synthesizer.md)
├── libs/utilities.py           # 📚 Tiktoken chunk splitting, 64KB SHA-256 de-dup, RRF fusion, Cross-Encoder
├── scripts/                    # ⚙️ ingest.py, migrate_multicloud.py, setup_* & migrate_pg_* cloud scripts
├── tests/                      # 🧪 Automated Offline Test Suite (120 Tests across 13 modules)
├── streamlit_app.py            # 🖥️ Interactive Web UI (PKCE auth, encrypted cookie session, live streaming)
└── schema.sql, Dockerfile, docker-compose.yml, requirements.txt
```
### 10.2. Master File & Symbol Cross-Reference
| System Layer | File Location | Key Symbols & Responsibilities |
| :--- | :--- | :--- |
| **Database Schema** | [`schema.sql`](file:///c:/src/enterprise-rag-pgvector-rbac/schema.sql) | DDL tables `documents`, `document_chunks`, `sdlc_outbox_events`, HNSW/GIN/B-Tree indexes. |
| **PostgreSQL Client** | [`app/db/manager.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/db/manager.py) | `DatabaseManager`, `hybrid_search`, `secure_search`, `claim_next_outbox_batch` (`SKIP LOCKED`), loop-scoped pool. |
| **Azure Search** | [`app/db/azure_search.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/db/azure_search.py) | `azure_hybrid_search`, OData collection role filtering (`allowed_roles/any(...)`). |
| **GCP Vertex AI Search** | [`app/db/gcp_search.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/db/gcp_search.py) | `gcp_hybrid_search`, Vertex AI `restricts` pre-filtering & two-tier JSON cache hydration. |
| **Databricks Search** | [`app/db/databricks_search.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/db/databricks_search.py) | `databricks_hybrid_search`, Mosaic AI Vector Search Unity Catalog `filters_json` RBAC. |
| **Multi-Model LLM** | [`app/db/llm.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/db/llm.py) | `get_openai_client`, `chat_completion_stream`, multi-cloud model abstraction & guardrails. |
| **Identity & PKCE** | [`app/auth/pkce.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/auth/pkce.py) | `generate_pkce_pair`, `encode_pkce_state`, `decode_pkce_state`, encrypted session cookie helpers. |
| **JWKS Security** | [`app/auth/jwks.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/auth/jwks.py) | `verify_jwt_token`, `get_allowed_issuers`, TTL public key cache manager (`leeway=60s`). |
| **Role Extraction** | [`app/auth/role_mapper.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/auth/role_mapper.py) | `resolve_user_roles`, `KNOWN_ROLES` entitlement validator & multi-IdP claim normalization. |
| **FastAPI Gateway** | [`app/main.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/main.py) | FastAPI lifecycle, `/api/v1/query`, `/healthz`, `/readyz`, `/webhooks/github`. |
| **FastMCP Server** | [`app/mcp/gateway.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/mcp/gateway.py) | `search_sdlc_context`, `propose_patch`, `MCPSearchRequest` (`extra='forbid'`), & `policy://sdlc-budget` resource. |
| **Observability** | [`app/observability.py`](file:///c:/src/enterprise-rag-pgvector-rbac/app/observability.py) | `setup_observability`, `record_chat_interaction`, Jaeger Badger LSM & Azure Monitor exporters. |
| **SDLC State Machine**| [`agent/workflow.py`](file:///c:/src/enterprise-rag-pgvector-rbac/agent/workflow.py) | `LangGraphSDLCWorkflow`, `compact_agent_context`, `TestTriagerSubagent` (`flash`), `CrossModelJudgeSubagent` (`pro`). |
| **Subagent Definitions**| [`.agent/agents/`](file:///c:/src/enterprise-rag-pgvector-rbac/.agent/agents/) | `test-triager.md` (`model: flash`), `gemini-judge.md` (`model: pro`), `arch-synthesizer.md` (`model: inherit`). |
| **AST & Rate Guardrails**| [`agent/guardrails.py`](file:///c:/src/enterprise-rag-pgvector-rbac/agent/guardrails.py) | `PolicyEngine`, `GroundingGuardrail`, `SlidingWindowRateLimiter`, `TokenCircuitBreaker`, AST & schema drift checks. |
| **Shared Utilities** | [`libs/utilities.py`](file:///c:/src/enterprise-rag-pgvector-rbac/libs/utilities.py) | `compute_file_hash`, `reciprocal_rank_fusion`, `rerank_candidates`, Tiktoken splitters. |
| **Ingestion & Migration**| [`scripts/ingest.py`](file:///c:/src/enterprise-rag-pgvector-rbac/scripts/ingest.py) | `ingest_documents`, [`scripts/migrate_multicloud.py`](file:///c:/src/enterprise-rag-pgvector-rbac/scripts/migrate_multicloud.py) unified cloud orchestrator. |
### 10.3. PostgreSQL 16 & pgvector DDL Reference (`schema.sql`)
```sql
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), document_id VARCHAR(100) NOT NULL UNIQUE, title VARCHAR(255) NOT NULL,
    source_path TEXT, file_hash CHAR(64) UNIQUE, file_type VARCHAR(16) DEFAULT 'markdown',
    allowed_roles JSONB NOT NULL DEFAULT '[]'::jsonb, metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS document_chunks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), document_id UUID NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_id VARCHAR(128) NOT NULL UNIQUE, chunk_index INT NOT NULL DEFAULT 0, content TEXT NOT NULL, token_count INT,
    embedding vector(1536) NOT NULL, embedding_model VARCHAR(100) DEFAULT 'text-embedding-3-large',
    tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED, created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw ON document_chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
CREATE INDEX IF NOT EXISTS idx_documents_allowed_roles_gin ON documents USING gin (allowed_roles jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_documents_file_hash ON documents (file_hash);
CREATE INDEX IF NOT EXISTS idx_chunks_content_tsv ON document_chunks USING gin (tsv);
CREATE TABLE IF NOT EXISTS sdlc_outbox_events (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), event_key VARCHAR(128) NOT NULL UNIQUE, aggregate_type VARCHAR(64) NOT NULL DEFAULT 'sdlc_webhook',
    payload JSONB NOT NULL DEFAULT '{}'::jsonb, status VARCHAR(32) NOT NULL DEFAULT 'PENDING', locked_by VARCHAR(128),
    locked_at TIMESTAMP WITH TIME ZONE, attempts INT NOT NULL DEFAULT 0, created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP, processed_at TIMESTAMP WITH TIME ZONE
);
CREATE INDEX IF NOT EXISTS idx_sdlc_outbox_pending ON sdlc_outbox_events (created_at ASC) WHERE status = 'PENDING';
```
### 10.4. Container & Observability Configuration Reference
```yaml
# docker-compose.yml — Persistent Jaeger Badger LSM + PostgreSQL 16 pgvector
version: "3.8"
services:
  jaeger:
    image: jaegertracing/all-in-one:latest
    container_name: jaeger
    user: "0:0"
    environment: [SPAN_STORAGE_TYPE=badger, BADGER_EPHEMERAL=false, BADGER_DIRECTORY_VALUE=/badger/data, BADGER_DIRECTORY_KEY=/badger/key, BADGER_SPAN_STORE_TTL=168h]
    ports: ["16686:16686", "4317:4317"]
    volumes: ["jaeger_data:/badger"]
    restart: unless-stopped
  postgres:
    image: pgvector/pgvector:pg16
    container_name: enterprise-rag-db
    environment: {POSTGRES_USER: rag_user, POSTGRES_PASSWORD: rag_password, POSTGRES_DB: enterprise_rag}
    ports: ["5432:5432"]
    volumes: ["pgdata:/var/lib/postgresql/data"]
    restart: unless-stopped
volumes: {jaeger_data: {}, pgdata: {}}
```
```dockerfile
# Dockerfile — Hardened Multi-Stage Non-Root Container
FROM python:3.11-slim AS builder
RUN pip install --no-cache-dir --user -r requirements.txt
FROM python:3.11-slim AS runner
RUN groupadd -g 10001 appgroup && useradd -u 10001 -g appgroup -m -s /bin/bash appuser
USER appuser
HEALTHCHECK --interval=30s --timeout=5s CMD curl -f http://localhost:8000/healthz || exit 1
```
### 10.5. Multi-Cloud `.env` & Migration Reference
```ini
RETRIEVAL_BACKEND="azure" # 'pgvector' | 'azure' | 'gcp' | 'databricks'
AZURE_OPENAI_ENDPOINT="https://oai-enterprise-rag.openai.azure.com/"
AZURE_SEARCH_ENDPOINT="https://search-enterprise-rag.search.windows.net"
AZURE_SEARCH_INDEX_NAME="enterprise-documents-index"
GCP_PROJECT_ID="gen-lang-client-0795078481"
GCP_INDEX_ENDPOINT_DOMAIN="1876216656.us-central1-226714713434.vdb.vertexai.goog"
GCP_DEPLOYED_INDEX_ID="enterprise_rag_index"
DATABRICKS_HOST="dbc-xxxx.cloud.databricks.com"
DATABRICKS_VECTOR_SEARCH_ENDPOINT_NAME="enterprise_vs_endpoint"
DATABRICKS_INDEX_NAME="main.enterprise_rag.document_chunks_index"
```

## 11. Disclaimer & Synthetic Data Security Notice
> [!CAUTION]
> **Data Security & Synthetic Assets**: All test documents, corporate financial summaries, and account figures referenced within this repository and test suite are **synthetic mock assets** generated solely for technical evaluation of Role-Based Access Control (RBAC) and vector similarity search. None of the indexed texts contain genuine Personally Identifiable Information (PII) or authentic material financial records. Always ensure telemetry scrubbers are enabled in enterprise production environments to redact sensitive tokens, authorization headers, and restricted document fragments prior to exporting spans to centralized tracing collectors.
