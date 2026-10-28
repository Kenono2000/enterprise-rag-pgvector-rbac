# 🛡️ Enterprise Zero-Trust RAG & Autonomous SDLC
| Live Artifact | Description | Access Link |
| :--- | :--- | :--- |
| **Interactive UI** | Shift-Left In-Database RBAC & Session Monitor | [enterprise-rag-pgvector-rbac.streamlit.app](https://enterprise-rag-pgvector-rbac.streamlit.app) |
| **API Docs** | Live OpenAPI / Interactive Swagger UI | [enterprise-rag-api-ksez.onrender.com/docs](https://enterprise-rag-api-ksez.onrender.com/docs) |
| **Source Code** | Auditable Source Repository & Offline Test Suite | [github.com/Kenono2000/enterprise-rag-pgvector-rbac](https://github.com/Kenono2000/enterprise-rag-pgvector-rbac) |

**Architect:** **[Ken Wong](https://www.linkedin.com/in/kenwong-architect/)** — Shift-left **In-Database Zero-Trust Vector RBAC** & **Autonomous Self-Healing SDLC Agent** (`PostgreSQL 16 + pgvector`, `FastAPI`, `Streamlit`, `OAuth 2.0 PKCE`, `JWKS`, `FastMCP`, `LangGraph`, `CrewAI`, `Hermes Agent`).\
**Quick Navigation:** [1. In-Database RBAC & Storage](#1-in-database-rbac-and-vector-storage-schemasql-appdb) · [2. Quickstart & Runtime Stack](#2-5-minute-quickstart-and-runtime-stack) · [3. Identity & Session Security](#3-identity-oauth-20-pkce-and-session-security-appauth) · [4. Ingestion & Hybrid RAG](#4-ingestion-pipeline-and-hybrid-rag-quality-scriptsingestpy-libs) · [5. Gateways, OTel & SDLC Agent](#5-gateways-observability-and-autonomous-sdlc-agent-app-agent) · [6. Multi-Cloud & Runbook](#6-multi-cloud-strategy-and-runbook)
## Complete System Architecture
```mermaid
%%{init: {'flowchart': {'nodeSpacing': 8, 'rankSpacing': 16, 'padding': 4}}}%%
flowchart LR
    subgraph Identity ["3. Identity & Auth"]
        direction TB
        UI["Streamlit (:8501) & Agents"] --> PKCE["OAuth 2.0 PKCE + JWKS<br/>& HMAC Cookie (15m/12h)"]
    end
    subgraph Gateways ["2 & 5. Gateways & OTel"]
        direction TB
        API["FastAPI (:8000) & FastMCP"] --> OTel["OpenTelemetry SDK<br/>(Jaeger Badger LSM)"]
    end
    subgraph RAGCore ["1 & 4. Ingest & In-DB RBAC"]
        direction TB
        PG["PG16 GIN RBAC + HNSW<br/>(SHA-256 Ingest)"] --> RRF["Hybrid RRF (k=60)<br/>+ Grounding Guard"]
    end
    subgraph CloudAndSDLC ["5 & 6. SDLC & Clouds"]
        direction TB
        SDLC["LangGraph + CrewAI<br/>+ Hermes SDLC Agent"]
        Clouds["Multi-Cloud Vector<br/>(Azure / GCP / DBX)"]
    end
    Identity --> Gateways --> RAGCore --> CloudAndSDLC
    style Identity fill:#fefce8,stroke:#ca8a04,stroke-width:1.5px
    style Gateways fill:#f0fdf4,stroke:#16a34a,stroke-width:1.5px
    style RAGCore fill:#f0f9ff,stroke:#0284c7,stroke-width:1.5px
    style CloudAndSDLC fill:#fdf4ff,stroke:#c026d3,stroke-width:1.5px
```
| Topic | Architectural Pillar | Core Engineering Pattern | Primary Security & Performance Outcome |
| :-: | :--- | :--- | :--- |
| **1** | **In-DB RBAC & Storage** | Pre-filtered GIN + HNSW iterative scan (`relaxed_order`) & 1536-d Matryoshka | Zero recall starvation, zero overfiltering, **50% RAM savings** (>98% recall). |
| **2** | **Quickstart & Runtime** | Event-loop-scoped `asyncpg` pools, `SKIP LOCKED` outbox & `/readyz` | Prevents closed-loop crashes; durable worker queue; Kubernetes probe ready. |
| **3** | **Identity & Sessions** | Stateless OAuth 2.0 PKCE, HMAC state & encrypted cookies | Survives F5 reloads & multi-worker scale-out with **zero Redis**; SOC-2 15m/12h bounds. |
| **4** | **Ingestion & Hybrid RAG** | 64KB SHA-256 de-dup, Dense + Sparse RRF (`k=60`) & `GroundingGuardrail` | `O(1)` skip for unchanged files; captures exact SKUs/error codes; verified citations. |
| **5** | **Gateways, OTel & SDLC** | Zero-Trust FastMCP, Jaeger Badger LSM & Tri-Paradigm SDLC (`LangGraph`/`CrewAI`/`Hermes`) | 60 req/min + 8K/50K token circuit breakers; AST-audited PRs; `SKILL.md` + ShareGPT RL export. |
| **6** | **Multi-Cloud & Runbook** | Quad-mode strategy (`pgvector`, `azure`, `gcp`, `databricks`) | Zero-downtime `.env` switching with native pre-filtering across all 4 engines. |
## 1. In-Database RBAC and Vector Storage (`schema.sql`, `app/db/`)
```mermaid
%%{init: {'flowchart': {'nodeSpacing': 8, 'rankSpacing': 16, 'padding': 4}}}%%
flowchart LR
    subgraph PostFilter ["❌ Standard Post-Filtering"]
        direction TB
        PF1["Unfiltered Vector Top-K"] --> PF2["Python RAM Filter<br/>(0 Hits & Memory Leak)"]
    end
    subgraph PreFilter ["✅ Shift-Left In-DB RBAC"]
        direction TB
        GIN["1. GIN Role Pre-Filter<br/>(allowed_roles ?| $2)"] --> HNSW["2. HNSW Iterative Scan<br/>(relaxed_order, 1536-d)"]
    end
    PostFilter -.->|"Replaced By"| PreFilter
    style PostFilter fill:#fee2e2,stroke:#ef4444,stroke-width:1.5px
    style PreFilter fill:#dcfce7,stroke:#16a34a,stroke-width:1.5px
```
```sql
SELECT d.document_id, d.title, c.chunk_index, c.content, d.allowed_roles, 1 - (c.embedding <=> $1::vector) AS similarity
FROM document_chunks c JOIN documents d ON c.document_id = d.id
WHERE d.allowed_roles ?| $2::text[] AND (c.embedding_model = 'text-embedding-3-large' OR c.embedding_model IS NULL)
ORDER BY c.embedding <=> $1::vector LIMIT $3;
```
* **No Recall Starvation & pgvector 0.8+ Iterative Scans**: PostgreSQL evaluates `WHERE d.allowed_roles ?| $2::text[]` via the **GIN Index** and automatically configures `SET hnsw.iterative_scan = 'relaxed_order'` (`max_scan_tuples = 20000`) per pooled connection—eliminating ANN overfiltering on selective roles while ensuring unauthorized rows never enter Python RAM.
* **SQL Injection & Empty-Role Guards**: Binds roles strictly as a parameterized `$2::text[]` array and returns `[]` immediately before DB execution if `user_roles` is empty.
* **Matryoshka 1536-d & Normalized Schema**: Truncates `text-embedding-3-large` from `3072` to `1536` dims (**50% RAM savings**, **>98% recall**) across normalized `documents` + `document_chunks` (`ON DELETE CASCADE`) tables (see [`schema.sql`](file:///c:/src/enterprise-rag-pgvector-rbac/schema.sql)).
## 2. 5-Minute Quickstart and Runtime Stack
```mermaid
%%{init: {'flowchart': {'nodeSpacing': 8, 'rankSpacing': 16, 'padding': 4}}}%%
flowchart LR
    subgraph DevBootstrap ["1. Bootstrap & Verify"]
        direction TB
        Venv["Install .venv & Deps"] --> Pytest["Run 124 Pytest Tests"]
    end
    subgraph Containers ["2. Docker Infrastructure"]
        direction TB
        PG16["PG16 + pgvector (:5432)"] --> Jaeger["Jaeger Badger (:16686)"]
    end
    subgraph Services ["3. App Runtime"]
        direction TB
        FastAPI["FastAPI (:8000) & FastMCP"] --> Streamlit["Streamlit UI (:8501)"]
    end
    DevBootstrap --> Containers --> Services
    style DevBootstrap fill:#f8fafc,stroke:#94a3b8,stroke-width:1.5px
    style Containers fill:#f0f9ff,stroke:#0284c7,stroke-width:1.5px
    style Services fill:#f0fdf4,stroke:#16a34a,stroke-width:1.5px
```
```powershell
git clone https://github.com/Kenono2000/enterprise-rag-pgvector-rbac.git && cd enterprise-rag-pgvector-rbac
python -m venv .venv && .\.venv\Scripts\Activate.ps1 && python -m pip install -r requirements.txt
python -m pytest -v                                                     # 1. Run full test suite (124 tests)
docker compose up -d && psql -U postgres -d enterprise_rag -f schema.sql # 2. Start PG16 + pgvector & Jaeger Badger
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload       # 3. Launch FastAPI Backend (:8000)
python -m streamlit run streamlit_app.py --server.port 8501              # 4. Launch Streamlit UI (:8501)
python -m app.mcp                                                        # 5. Launch FastMCP Gateway (stdio/SSE)
python -m agent status                                                   # 6. Run Hermes + CrewAI + LangGraph SDLC CLI
```
* **Local Endpoints**: Streamlit UI (`http://localhost:8501`) · Swagger Docs (`http://localhost:8000/docs`) · Health Probes (`/healthz`, `/readyz`) · Telemetry (`/api/v1/metrics/observability`) · Jaeger UI (`http://localhost:16686`).
* **Loop-Scoped Async Concurrency**: `DatabaseManager` and `get_openai_client()` scope connection pools to `asyncio.get_running_loop()`, preventing `RuntimeError: Event loop is closed` across Streamlit threads.
## 3. Identity, OAuth 2.0 PKCE, and Session Security (`app/auth/`)
```mermaid
%%{init: {'sequence': {'mirrorActors': false, 'actorMargin': 18, 'boxMargin': 4, 'messageMargin': 14}}}%%
sequenceDiagram
    autonumber
    actor Browser as Browser / Streamlit
    participant Google as Google OAuth 2.0
    participant App as App Server (app/auth/)
    participant JWKS as Google JWKS
    Browser->>Google: Redirect /auth (S256 code_challenge + HMAC state)
    Google->>Browser: User consents -> ?code=XXX&state=YYY
    Browser->>App: Verify HMAC state & exchange code + verifier
    Google-->>App: Returns {id_token, access_token, refresh_token}
    App->>JWKS: Verify RS256 signature (leeway=60s) & map roles
    App->>Browser: Set encrypted cookie (15m idle / 12h max)
```
* **Stateless HMAC PKCE State**: `encode_pkce_state()` signs `{b64_payload}.{sig}` (300s TTL) with HMAC-SHA256, surviving OAuth redirects and multi-worker restarts without Redis.
* **F5 Reload Resilience**: Compresses (`zlib`) and HMAC-signs session tokens into the `enterprise_rag_session` cookie, rehydrating `st.session_state` and silently rotating expired tokens on browser refresh.
* **Multi-IdP JWKS & SOC-2 Bounds**: Validates RS256 signatures (`leeway=60s`), maps claims across Google, Azure AD, Okta, Cognito, and Keycloak against `KNOWN_ROLES`, and enforces a **15-minute idle timeout** and **12-hour hard ceiling**.
## 4. Ingestion Pipeline and Hybrid RAG Quality (`scripts/ingest.py`, `libs/`)
```mermaid
%%{init: {'flowchart': {'nodeSpacing': 8, 'rankSpacing': 16, 'padding': 4}}}%%
flowchart LR
    subgraph Stage1 ["1. SHA-256 Intake"]
        direction TB
        Hash["64KB SHA-256 Hash"] --> Check{"Unchanged?"}
        Check -->|Yes| Skip["Skip (O(1) Bypass)"]
    end
    subgraph Stage2 ["2. Split & Embed"]
        direction TB
        Split["Tiktoken Split (800)"] --> Embed["Batch Embed (64)<br/>+ Upsert PG16"]
    end
    subgraph Stage3 ["3. Hybrid RAG & Guard"]
        direction TB
        RRF["Dense + Sparse RRF"] --> Guard["Cross-Encoder &<br/>GroundingGuardrail"]
    end
    Check -->|Modified| Split
    Embed --> RRF
    style Stage1 fill:#f8fafc,stroke:#94a3b8,stroke-width:1.5px
    style Stage2 fill:#f0f9ff,stroke:#0284c7,stroke-width:1.5px
    style Stage3 fill:#fdf4ff,stroke:#c026d3,stroke-width:1.5px
    style Skip fill:#fee2e2,stroke:#ef4444,stroke-width:1.5px
    style Guard fill:#dcfce7,stroke:#16a34a,stroke-width:1.5px
```
* **Skip Unchanged Files (SHA-256 Hashing)**: Hashes files in 64KB blocks (`O(1)` lookup) to skip unchanged documents with zero API calls, and automatically replaces old chunks when a file is updated.
* **Table-Safe Chunking & Rate-Limit Retry**: Splits documents into 800-token chunks without breaking Markdown tables, and embeds in 64-chunk batches with automatic exponential backoff (`tenacity`) on HTTP `429` rate limits.
* **Hybrid Search (Semantic + Keyword RRF)**: Combines vector search (meaning) with full-text search (exact SKUs/error codes like `ERR-502`) using Reciprocal Rank Fusion (`k=60`), pre-filtered by user role in PostgreSQL.
* **Re-Ranking & Citation Guardrail (`GroundingGuardrail`)**: Re-ranks top results with a `CrossEncoder` and requires every answer to cite `[Doc: <Title>, Chunk <Index>]`—explicitly refusing to answer when context is missing.
## 5. Gateways, Observability, and Autonomous SDLC Agent (`app/`, `agent/`)
```mermaid
%%{init: {'flowchart': {'nodeSpacing': 8, 'rankSpacing': 16, 'padding': 4}}}%%
flowchart LR
    subgraph Intake ["1. Webhook & Recall"]
        direction TB
        Hook["HMAC Webhook"] --> Init["Init & Recall<br/>Hermes Skills"]
    end
    subgraph Gen ["2. CrewAI Architect"]
        direction TB
        Propose["Propose Patch<br/>(model: inherit)"] --> Apply["Snapshot & Apply<br/>(Path Guard)"]
    end
    subgraph Audit ["3. CrewAI Pro Judge"]
        direction TB
        Inspect["Deep AST + Judge<br/>(model: pro)"] -->|Secret/Max| Reject["Atomic Rollback"]
    end
    subgraph Verify ["4. Flash Triage & Hermes"]
        direction TB
        Test{"test-triager<br/>(30s Timeout)"} -->|Retry < 3| Repair["Repair (<=3x)"]
        Test -->|Passed| Hermes["Hermes SKILL.md<br/>+ HITL Gate / PR"]
    end
    Intake --> Gen --> Audit -->|Pass| Verify
    style Intake fill:#f8fafc,stroke:#94a3b8,stroke-width:1.5px
    style Gen fill:#f0f9ff,stroke:#0284c7,stroke-width:1.5px
    style Audit fill:#fefce8,stroke:#ca8a04,stroke-width:1.5px
    style Verify fill:#fdf4ff,stroke:#c026d3,stroke-width:1.5px
    style Reject fill:#fee2e2,stroke:#ef4444,stroke-width:1.5px
    style Hermes fill:#dcfce7,stroke:#22c55e,stroke-width:1.5px
```
* **Zero-Trust FastMCP Gateway (`app/mcp/gateway.py`)**: Exposes `search_sdlc_context`, `propose_patch`, `run_sdlc_crew`, `recall_hermes_skills`, and `policy://sdlc-budget` over `stdio`/`SSE` with `ConfigDict(extra="forbid")` schemas (`MCPSearchRequest`, `MCPPatchRequest`, `MCPSDLCCrewRequest`, `MCPHermesSkillRequest`), 60 req/min `SlidingWindowRateLimiter`, and 8K/50K `TokenCircuitBreaker`.
* **Full-Stack OpenTelemetry (`app/observability.py`)**: Streams OTLP gRPC spans (`:4317`) to **Jaeger** (persistent Badger LSM disk store, 7-day TTL) and **Azure Application Insights**, backed by a 1,000-event ring buffer (`GET /api/v1/metrics/observability`) and non-root `Dockerfile` (`UID 10001`).
* **Tri-Paradigm SDLC Workflow (`agent/workflow.py`)**: Unites **LangChain/LangGraph** (`LangGraphSDLCWorkflow` cyclic state machine + `MemorySaver` + atomic `rollback_patches` + per-node OTel spans), **CrewAI** (`SDLCCrewOrchestrator` role-based crew + `build_crewai_crew`/`kickoff_crew` upstream `crewai` SDK adapter: `Principal SDLC Architect` [`inherit`], `Lead Security & AST Auditor` [`pro`], and `Site Reliability & Pytest Triager` [`flash`]), and **Hermes Agent** (`HermesSkillSynthesizer` closed-loop `recall_relevant_skills`, portable `SKILL.md` distillation, and ShareGPT RL export) guarded by `PolicyEngine` (deep AST blocking `eval`/`exec`/`os.system`/`subprocess(shell=True)`/`pickle.loads`, protected-path guards, 30s subprocess timeouts, and `ApprovalCard` HITL risk gating).
## 6. Multi-Cloud Strategy and Runbook
* **Zero-Downtime Cutover & Failover**: Switch `RETRIEVAL_BACKEND` in `.env` (`pgvector` | `azure` | `gcp` | `databricks`) or run `python scripts/migrate_multicloud.py --target all`.
* **Incident Runbook**: On DB latency alerts in Jaeger (`http://localhost:16686`), fail over `RETRIEVAL_BACKEND` in `.env`; on JWKS key rotation, restart the auth worker to flush `JWKSClient`; verify Badger LSM persistence via `docker compose restart jaeger`.
```mermaid
%%{init: {'flowchart': {'nodeSpacing': 8, 'rankSpacing': 16, 'padding': 4}}}%%
flowchart LR
    subgraph Router ["1. Backend Toggle"]
        direction TB
        Toggle["RETRIEVAL_BACKEND<br/>(.env / Zero Downtime)"]
    end
    subgraph Engines ["2. Cloud Vector Engines"]
        direction TB
        LocalAndAz["pgvector (?| GIN)<br/>azure (OData any)"] --> GcpAndDbx["gcp (ScaNN restricts)<br/>databricks (filters_json)"]
    end
    subgraph Runbook ["3. SRE Failover"]
        direction TB
        Alert["OTel / JWKS Alert"] --> Action["Switch Backend or<br/>Flush JWKS Cache"]
    end
    Router --> Engines --> Runbook
    style Router fill:#fefce8,stroke:#ca8a04,stroke-width:1.5px
    style Engines fill:#f0f9ff,stroke:#0284c7,stroke-width:1.5px
    style Runbook fill:#dcfce7,stroke:#16a34a,stroke-width:1.5px
```
| Backend (`RETRIEVAL_BACKEND`) | Vector & Hybrid Engine | In-Database RBAC Pre-Filter | LLM & Observability |
| :--- | :--- | :--- | :--- |
| **`pgvector`** (Local) | PG16 HNSW + `tsvector` RRF | `WHERE allowed_roles ?| $2::text[]` | OpenAI `gpt-4o` + Jaeger Badger LSM |
| **`azure`** (Microsoft Azure) | Azure AI Search + Semantic Ranker | OData `allowed_roles/any(r: ...)` | Azure OpenAI `gpt-4o` + App Insights |
| **`gcp`** (Google Cloud) | Vertex AI ScaNN + Ranking API | ScaNN `restricts` (`allowList`) | Gemini 1.5 Pro + Cloud Trace |
| **`databricks`** (Databricks) | Mosaic AI Vector Search (Delta Sync) | Unity Catalog `filters_json` (`OR`) | Llama 3.1 70B + MLflow Tables |
