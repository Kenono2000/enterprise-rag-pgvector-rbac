# 🛡️ Enterprise Zero-Trust RAG & Autonomous SDLC

> **Architect:** **[Ken Wong](https://www.linkedin.com/in/kenwong-architect/)**  
> An enterprise-grade, shift-left reference implementation combining **In-Database Zero-Trust Vector RBAC** with an **Autonomous Self-Healing SDLC Agent**.  
> **Tech Stack:** PostgreSQL 16 + pgvector, FastAPI, Streamlit, Google OAuth 2.0 PKCE, Google JWKS, FastMCP, LangGraph.

---

## 🚀 Live Interactive Artifacts

| Component | Description | Access Link |
| :--- | :--- | :--- |
| **Interactive UI** | Shift-Left In-Database RBAC & Session Monitor | [enterprise-rag-pgvector-rbac.streamlit.app](https://enterprise-rag-pgvector-rbac.streamlit.app) |
| **API Docs** | Live OpenAPI / Interactive Swagger UI | [enterprise-rag-api-ksez.onrender.com/docs](https://enterprise-rag-api-ksez.onrender.com/docs) |
| **Source Code** | Auditable Source Repository & Offline Test Suite | [github.com/Kenono2000/enterprise-rag-pgvector-rbac](https://github.com/Kenono2000/enterprise-rag-pgvector-rbac) |

---

## 📑 Table of Contents

1. [The Core Value: Why In-Database RBAC?](#-the-core-value-why-in-database-rbac)
2. [System Architecture](#️-system-architecture)
3. [Codebase Organization](#-codebase-organization)
4. [Architectural Deep Dive: The 8 Engineering Layers](#-architectural-deep-dive-the-8-engineering-layers)
   - [Layer 1: Database & pgvector RBAC (`schema.sql` & `app/db/`)](#layer-1-database--pgvector-rbac-schemasql--appdb)
   - [Layer 2: Identity, Tokens & Session Security (`app/auth/`)](#layer-2-identity-tokens--session-security-appauth)
   - [Layer 3: High-Performance Ingestion Pipeline (`scripts/ingest.py` & `libs/utilities.py`)](#layer-3-high-performance-ingestion-pipeline-scriptsingestpy--libsutilitiespy)
   - [Layer 4: RAG Quality, Hybrid Search & Grounding Guardrails](#layer-4-rag-quality-hybrid-search--grounding-guardrails)
   - [Layer 5: FastAPI Backend & Streamlit Streaming Frontend](#layer-5-fastapi-backend--streamlit-streaming-frontend)
   - [Layer 6: Observability, Configuration & Container Hardening](#layer-6-observability-configuration--container-hardening)
   - [Layer 7: FastMCP Agent Gateway (`app/mcp/`)](#layer-7-fastmcp-agent-gateway-appmcp)
   - [Layer 8: Autonomous Self-Healing SDLC Agent (`agent/`)](#layer-8-autonomous-self-healing-sdlc-agent-agent)
5. [5-Minute Quickstart](#-5-minute-quickstart)
6. [Testing & Verification Guide (96 Tests: 95 Passed, 1 Skipped)](#-testing--verification-guide-96-tests-95-passed-1-skipped)
7. [Solved Engineering Pitfalls & Troubleshooting](#️-solved-engineering-pitfalls--troubleshooting)

---

## 💡 The Core Value: Why In-Database RBAC?

Traditional enterprise RAG architectures filter permissions **after** vector retrieval in application memory. This creates two catastrophic flaws:

```
❌ Standard Post-Filtering:
[Query] ──► [Vector DB: Top-K] ──► [Python App Filters by Role] ──► [LLM Context]
                                          │
                                          └─► Context Eviction & Memory Leaks

✅ Zero-Trust In-Database RBAC:
[Query] ──► [Verified JWT] ──► [PostgreSQL: GIN Filter + HNSW Scan] ──► [LLM Context]
                                          │
                                          └─► Unauthorized data never leaves DB
```

1. **Eliminates Recall Starvation**: If top-$K$ documents belong to restricted tiers, post-filtering drops them all in Python memory—returning zero results even when authorized lower-ranked documents exist.
2. **Zero Memory Leaks**: In-database RBAC executes `WHERE allowed_roles ?| $user_roles` **before** vector distance calculation. Unauthorized documents are never read from disk into buffer cache, never sent over TLS, and never loaded into application RAM.

---

## 🏛️ System Architecture

```mermaid
flowchart TB
    subgraph Client ["Client & Consumer Layer"]
        browser["Streamlit UI / Web Client<br/>(localhost:8501)"]
        mcp_client["AI Agent / Cursor / Claude Desktop"]
    end

    subgraph Identity ["Identity & Session Security"]
        google["Google OAuth 2.0 PKCE<br/>(accounts.google.com)"]
        jwks["Google JWKS (RS256)<br/>clock skew leeway=60s"]
        cookie["Encrypted Session Cookie<br/>(F5 reload persistence + 15m idle)"]
    end

    subgraph Backend ["FastAPI Zero-Trust Core (app/)"]
        api["API Gateway (POST /api/v1/query)<br/>Dependency: get_current_user"]
        embed["Embedding Engine<br/>text-embedding-3-large (1536-d)"]
        pool["Loop-Aware asyncpg Pool"]
    end

    subgraph Database ["PostgreSQL 16 + pgvector"]
        db[("documents + document_chunks<br/>• GIN: allowed_roles jsonb_path_ops<br/>• HNSW: embedding vector_cosine_ops")]
    end

    subgraph Agent ["Autonomous SDLC Agent (agent/)"]
        langgraph["LangGraph State Machine<br/>propose ➔ apply ➔ audit ➔ test ➔ repair"]
        guardrails["PolicyEngine<br/>Deterministic AST + Secret Scanner"]
    end

    browser -->|1. PKCE Auth Code| google
    google -->|2. RS256 ID Token| browser
    browser -->|3. Encrypted Cookie / Bearer| cookie
    browser -->|4. Authenticated Request| api
    api -->|5. Verify Token & Leeway| jwks
    api -->|6. Generate Embedding| embed
    api -->|7. In-DB RBAC SQL| pool
    pool -->|8. GIN Filter + Cosine Distance| db
    db -->|9. Authorized Top-K Only| api
    api -->|10. Grounded Response| browser

    mcp_client -->|Governed Tool Call| api
    Agent -->|Context Hydration| api

    style Database fill:#f9f,stroke:#333,stroke-width:2px
    style Identity fill:#dfd,stroke:#333,stroke-width:2px
    style Backend fill:#f0f8ff,stroke:#007acc,stroke-dasharray: 5 5
    style Agent fill:#fff9c4,stroke:#fbc02d,stroke-width:2px
```

---

## 📂 Codebase Organization

```text
enterprise-rag-pgvector-rbac/
├── app/                        # 🛡️ Zero-Trust RAG Microservice
│   ├── auth/                   # Identity: PKCE, JWKS verification, session cookies, role mapping
│   ├── db/                     # Data & AI: asyncpg pooling, pgvector search, OpenAI & local mocks
│   ├── mcp.py                  # FastMCP tools & policy resources for external AI agents
│   ├── observability.py        # Observability metrics, execution timers, and tracing
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
│   └── ingest.py               # Enterprise multi-format batch ingestion with SHA-256 change detection
│
├── tests/                      # 🧪 Automated Test Suite (96 Tests, 100% Offline)
│   ├── test_auth.py            # PKCE cryptography, JWKS leeway, session cookie tests
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

---

## 🧱 Architectural Deep Dive: The 8 Engineering Layers

### Layer 1: Database & pgvector RBAC (`schema.sql` & `app/db/`)

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

### Layer 2: Identity, Tokens & Session Security (`app/auth/`)

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
flowchart TD
    Check[Session Event / Periodic Check] --> Idle{Idle > 15 minutes?}
    Idle -->|Yes| Terminate[Terminate Session:<br/>Wipe Cookie + Redirect to Login]
    Idle -->|No| Ceiling{Elapsed > 12 hours?}
    Ceiling -->|Yes| Terminate
    Ceiling -->|No| Refresh[Silent Token Refresh via Google /token]
    Refresh --> OK[Session Active & Protected]
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

### Layer 3: High-Performance Ingestion Pipeline (`scripts/ingest.py` & `libs/utilities.py`)

The ingestion pipeline transforms raw documents into high-dimensional vector representations stored within the normalized PostgreSQL schema, enforcing change detection, semantic boundary preservation, and fault tolerance:

```mermaid
flowchart TD
    Raw[Raw Documents: PDF, MD, DOCX] --> Hash[compute_file_hash: 64KB Chunk SHA-256]
    Hash --> Check{Exists in documents table?}
    Check -->|Same Hash & Exists| Skip[Skip: Unchanged Content]
    Check -->|Modified Hash or New| Split[split_chunks: Tiktoken-Aware Semantic Chunking]
    Split --> Meta[Attach Chunk Metadata: page, chunk_index, source, document_id]
    Meta --> Batch[Batch Texts: 64-128 Chunks/Call]
    Batch --> Embed[embed_chunks_with_retry: Tenacity Exponential Backoff 429/503]
    Embed --> Master[Upsert documents Master Record]
    Master --> Clean[Purge Stale document_chunks for document_id]
    Clean --> Insert[Batch Insert document_chunks with HNSW Vectors]
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

### Layer 6: Observability, Configuration & Container Hardening

#### 1. Configuration Validation via Pydantic BaseSettings (`app/config.py`)
`app/config.py` uses `pydantic_settings.BaseSettings` to validate environment variables, secrets, and connection parameters at application startup. Missing credentials or malformed URIs fail fast during boot rather than intermittently at runtime.

#### 2. Enterprise Observability, OpenTelemetry & Jaeger Tracing (`app/observability.py`)
* **Dual-Tier Tracing Architecture**:
  * **Tier 1 (Fallback)**: High-performance structured metric logging with an in-memory bounded ring buffer (last 1,000 events) accessible via `GET /api/v1/metrics/observability`.
  * **Tier 2 (OpenTelemetry / Jaeger)**: Automatic OTLP export (`BatchSpanProcessor` + `OTLPSpanExporter` to `http://localhost:4317`) when `OTEL_ENABLED=true`.
* **Full Context Capture in Traces**:
  * Captures the user's natural language question (`rag.question`) and synthesized LLM response (`rag.response`) as both **OpenTelemetry Span Tags** and timeline **Span Events** (`user_question`, `ai_response`).
  * Attaches verified RBAC roles (`rag.roles`), LLM model name (`rag.model`), token consumption, and execution duration (`rag.duration_ms`).
* **FastAPI Request Middleware (`app/main.py`)**:
  * Inbound HTTP requests automatically create trace spans (`HTTP <METHOD> <PATH>`) logging client IP, status codes, and endpoint execution duration.
* **FastMCP Tool Tracing (`app/mcp/gateway.py`)**:
  * MCP tool calls (`search_sdlc_context`, `propose_patch`) emit dedicated spans (`mcp_tool.<tool_name>`) capturing arguments, sanitizing credentials, and logging results.
* **Persistent Jaeger Storage via Badger (`docker-compose.yml`)**:
  * Jaeger runs with `SPAN_STORAGE_TYPE=badger` backed by Docker volume `jaeger_data:/badger` (`user: "0:0"`).
  * Traces and RAG chat interactions persist across container restarts and system reboots with a 7-day retention TTL (`BADGER_SPAN_STORE_TTL=168h`).

#### 3. Hardened Multi-Stage Dockerfile (`Dockerfile`)
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

#### 4. Automated Integration Testing (`testcontainers-python`)
`tests/test_integration_pgvector.py` provides end-to-end integration testing against real database containers (`pgvector/pgvector:pg16`), verifying that `schema.sql` initializes extensions, creates tables, and executes HNSW and GIN queries accurately in CI environments.


---

### Layer 7: FastMCP Agent Gateway (`app/mcp/`)

FastMCP standardizes tool and resource access for external AI coding agents (Claude Desktop, Cursor, CLI agents):

| Primitive | Signature | Function |
| :--- | :--- | :--- |
| **Tool** | `search_sdlc_context(question, auth_token, user_roles)` | Authenticates calling agent via Google ID token and returns in-database RBAC-filtered knowledge base snippets. |
| **Tool** | `propose_patch(branch_name, patch_content, auth_token)` | Validates submitter identity and writes unified diff modifications to a feature branch. |
| **Resource** | `policy://sdlc-budget` | Serves operational constraints: maximum tokens per issue (`50,000`), maximum execution steps (`10`), and allowed tools. |

---

### Layer 8: Autonomous Self-Healing SDLC Agent (`agent/`)

The autonomous agent listens to GitHub issue webhooks, writes code patches, audits them statically, runs tests, and autonomously repairs bugs:

```mermaid
stateDiagram-v2
    [*] --> initialize
    initialize --> propose_patches
    propose_patches --> apply_patches
    apply_patches --> audit_patches
    
    audit_patches --> run_tests : Security Gate PASSED
    audit_patches --> [*] : Security Gate FAILED (Policy Violation)
    
    run_tests --> finalize : Tests PASSED (Clean Commit & PR)
    run_tests --> repair_patches : Tests FAILED (Attempts < Max)
    run_tests --> [*] : Max Attempts Reached
    
    repair_patches --> apply_patches
    finalize --> [*]
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

## ⚡ 5-Minute Quickstart

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

### 2. Run Automated Verification (96 Tests)
All tests run **100% offline** with zero external network or API dependencies:
```powershell
python -m pytest -v
```

### 3. Launch Services
```powershell
# Start PostgreSQL 16 + pgvector and Persistent Jaeger Tracing
docker compose up -d

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

## 🧪 Testing & Verification Guide (96 Tests: 95 Passed, 1 Skipped)

```text
tests/test_agent.py                     ......                                           [  6%]
tests/test_auth.py                      ..................................               [ 42%]
tests/test_database_schema.py           ......                                           [ 48%]
tests/test_hybrid_search.py             ......                                           [ 54%]
tests/test_ingest.py                    .........                                        [ 64%]
tests/test_integration_pgvector.py      s.                                               [ 66%]
tests/test_mcp_auth.py                  ..........                                       [ 76%]
tests/test_observability_and_health.py  .......                                          [ 83%]
tests/test_rag.py                       ....                                             [ 87%]
tests/test_security_rbac.py             .....                                            [ 92%]
tests/test_utilities.py                 .......                                          [100%]
================== 95 passed, 1 skipped, 1 warning in 22.04s ===================
```

### Test Suite Breakdown

| Module | Tests | Key Invariants Verified |
| :--- | :---: | :--- |
| **`tests/test_hybrid_search.py`** | 6 | • Reciprocal Rank Fusion (RRF) math validation.<br/>• Zero-Trust empty role short-circuiting.<br/>• Heuristic & cross-encoder candidate re-ranking.<br/>• GroundingGuardrail citation and missing context admission checks. |
| **`tests/test_observability_and_health.py`** | 7 | • Liveness (`/healthz`) and readiness (`/readyz`) probes.<br/>• Telemetry endpoint (`/api/v1/metrics/observability`).<br/>• 503 DB failure handling.<br/>• Pydantic `BaseSettings` validation.<br/>• `ObservabilityTracer` metric recording.<br/>• Token streaming sync and async generators. |
| **`tests/test_integration_pgvector.py`** | 2 | • Testcontainers `pgvector/pgvector:pg16` end-to-end integration harness.<br/>• Verification of schema.sql DDL, HNSW index, and GIN full-text search. |
| **`tests/test_database_schema.py`** | 6 | • Normalized table schemas (`documents` & `document_chunks`).<br/>• `ON DELETE CASCADE` foreign key relationship.<br/>• HNSW vector index (`m=16, ef=64`) & GIN role index.<br/>• GIN full-text index on `tsv`.<br/>• B-tree file hash de-duplication index.<br/>• Cosine similarity calculation benchmark simulation. |
| **`tests/test_security_rbac.py`** | 5 | • SQL injection immunity in vector search.<br/>• Parameterized array containment (`$2::text[]`).<br/>• Zero-Trust empty role short-circuiting.<br/>• Header validation and injection filtering. |
| **`tests/test_auth.py`** | 34 | • RFC 7636 PKCE `code_verifier` & `code_challenge` derivation.<br/>• Stateless HMAC-SHA256 OAuth state generation & expiration (300s TTL).<br/>• Google JWKS certificate caching & `leeway=60s` clock skew tolerance.<br/>• Multi-source role claim extraction (`app_roles`, `roles`, `groups`, `cognito:groups`, `realm_access.roles`).<br/>• Enterprise JWKS issuer validation & rejection of untrusted issuers.<br/>• **Session Cookie Encoding**: Roundtrip compression, signature tampering rejection, expired TTL handling, and malformed cookie rejection. |
| **`tests/test_rag.py`** | 4 | • Health check status.<br/>• Strict 401 rejection when unauthenticated.<br/>• Dev header fallback (`X-User-Roles`).<br/>• End-to-end vector retrieval & RBAC filtering. |
| **`tests/test_mcp_auth.py`** | 10 | • FastMCP token validation and unauthenticated caller rejection.<br/>• Verified role extraction from ID tokens for tool execution.<br/>• Identity verification on patch submission. |
| **`tests/test_agent.py`** | 6 | • GitHub webhook HMAC-SHA256 verification.<br/>• Webhook JSON parsing into typed models.<br/>• Deterministic secret scanning (API keys, private keys).<br/>• AST static inspection (`eval`, `exec`, `__import__`).<br/>• Sandbox path traversal prevention.<br/>• Full LangGraph self-healing test repair cycle. |
| **`tests/test_ingest.py`** | 9 | • Pre-ingestion SHA-256 de-duplication, modified file re-indexing detection, force flag bypass, stem matching, chunk prefix detection. |
| **`tests/test_utilities.py`** | 7 | • Multi-format loaders (`.pdf`, `.md`, `.docx`), tokenizer-aware chunk splitting, chunk metadata attribution, 64KB block hashing, and tenacity retry on 429 rate limits. |
| **Total** | **96** | **95 Passed, 1 Skipped** |

---

## 🛠️ Solved Engineering Pitfalls & Troubleshooting

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
| **Jaeger Badger `mkdir /badger/key: permission denied`** | Docker mounts root-owned named volume while container ran as non-root user. | **Container User Mapping (`user: "0:0"`)**: Run Jaeger with root user context to initialize Badger LSM value log directories and SSTable index keys. |
| **Jaeger Trace Loss on Container Restart** | Default all-in-one image stores traces in ephemeral memory. | **Persistent Badger Storage**: Configured `SPAN_STORAGE_TYPE=badger` with Docker volume `jaeger_data:/badger` and 7-day TTL retention. |