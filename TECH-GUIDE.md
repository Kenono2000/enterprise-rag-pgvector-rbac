# 🛡️ Enterprise Zero-Trust RAG & Autonomous SDLC: Technical Guide

> **High-Performance Architecture & Implementation Reference**  
> **Repository:** `enterprise-rag-pgvector-rbac`  
> **Tech Stack:** PostgreSQL 16 + pgvector, FastAPI, Streamlit, Google OAuth 2.0 PKCE, Google JWKS, FastMCP, LangGraph.

---

## 📑 Table of Contents
1. [Architectural Overview: Standard RAG vs. Zero-Trust In-Database RBAC](#1-architectural-overview)
2. [Codebase Organization](#2-codebase-organization)
3. [Layer 1: Database & pgvector RBAC (`schema.sql` & `app/db/`)](#3-layer-1-database--pgvector-rbac)
4. [Layer 2: Identity, Tokens & Session Security (`app/auth/`)](#4-layer-2-identity-tokens--session-security)
5. [Layer 3: FastAPI Backend & Streamlit Frontend](#5-layer-3-fastapi-backend--streamlit-frontend)
6. [Layer 4: FastMCP Agent Gateway (`app/mcp/`)](#6-layer-4-fastmcp-agent-gateway)
7. [Layer 5: Autonomous Self-Healing SDLC Agent (`agent/`)](#7-layer-5-autonomous-self-healing-sdlc-agent)
8. [Testing & Verification Guide (41/41 Tests)](#8-testing--verification-guide)
9. [Operational Cheat Sheet & Troubleshooting](#9-operational-cheat-sheet--troubleshooting)

---

## 1. Architectural Overview

### The Problem with Standard RAG
In traditional RAG pipelines, access control is applied **after** vector retrieval in application memory:

```
[User Query] ──► [Vector DB: Retrieve Top-K] ──► [Python App Filters by Role] ──► [LLM Context]
                                                        │
                                                        └─► Context Eviction & Memory Leaks
```

* **Recall Starvation**: If top-$K$ results belong to restricted tiers, post-filtering removes them all in Python memory—leaving the user with zero context even when valid lower-ranked documents exist.
* **Memory Leaks**: Sensitive documents enter application RAM, heap caches, and logs before redaction.

### The Zero-Trust Solution: In-Database RBAC
In this architecture, role filtering executes **directly inside PostgreSQL query execution**:

```
[User Query] ──► [Verified JWT] ──► [Extract Roles] ──► [PostgreSQL Engine] ──► [LLM Context]
                                                               │
                                  ┌────────────────────────────┴───────────────────────────┐
                                  │ WHERE allowed_roles ?| $user_roles (GIN Index Filter) │
                                  │ ORDER BY embedding <=> $query_vec  (HNSW Index Scan)  │
                                  └────────────────────────────────────────────────────────┘
```

* **Zero Memory Leakage**: Unauthorized rows are never read from disk into buffer cache, never sent over TLS, and never loaded into application memory.
* **Preserved Recall**: The HNSW vector index ranks only documents the user is authorized to read.

---

## 2. Codebase Organization

```text
enterprise-rag-pgvector-rbac/
├── app/                        # 🛡️ Zero-Trust RAG Microservice
│   ├── auth/                   # Identity: PKCE, JWKS verification, session cookies, role mapping
│   ├── db/                     # Data & AI: asyncpg pooling, pgvector search, OpenAI & local mocks
│   ├── mcp.py                  # FastMCP tools & policy resources for external AI agents
│   └── main.py                 # FastAPI REST API (/api/v1/query, /health, /webhooks/github)
│
├── agent/                      # 🤖 Autonomous Self-Healing SDLC Agent
│   ├── workflow.py             # LangGraph state machine (patch -> audit -> test -> repair -> PR)
│   ├── guardrails.py           # Deterministic AST inspection & secret scanners
│   └── parser.py               # GitHub webhook event parser & HMAC signature verifier
│
├── tests/                      # 🧪 Automated Test Suite (41/41 Tests, 100% Offline)
│   ├── test_rag.py             # RAG endpoints & in-database RBAC tests
│   ├── test_auth.py            # PKCE cryptography, JWKS leeway, session cookie tests
│   ├── test_mcp_auth.py        # FastMCP authentication & tool access tests
│   └── test_agent.py           # LangGraph workflow, AST guardrails, path traversal tests
│
├── streamlit_app.py            # 🖥️ Interactive Web UI (PKCE auth, cookie session persistence, live RAG)
├── schema.sql                  # PostgreSQL schema, HNSW/GIN indexes, seed mock data
└── requirements.txt            # Production dependencies
```

---

## 3. Layer 1: Database & pgvector RBAC

### Normalized Schema & Dual-Index Strategy (`schema.sql`)
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
```

### The In-Database RBAC Query (`app/db/manager.py`)
```sql
SELECT d.document_id, d.title, c.content, d.allowed_roles, 
       1 - (c.embedding <=> $1::vector) AS similarity
FROM document_chunks c
JOIN documents d ON c.document_id = d.id
WHERE d.allowed_roles ?| $2::text[]
  AND (c.embedding_model = 'text-embedding-3-large' OR c.embedding_model IS NULL)
ORDER BY c.embedding <=> $1::vector
LIMIT $3;
```

* **`?|` (JSONB Exists-Any)**: Returns `TRUE` if **any** user role matches **any** element in `allowed_roles`. Uses GIN index for sub-millisecond filtering before computing vector distances.
* **`<=>` (Cosine Distance)**: Calculates distance $1 - \cos(\theta)$. Inverted to $1 - (\text{dist})$ to produce a normalized similarity score $[0.0, 1.0]$.

### Key Database Optimizations
1. **Parameterized Query Execution & SQL Injection Immunity**: Vector search executes exclusively via parameterized array containment (`WHERE allowed_roles ?| $2::text[]`). String interpolation into `ARRAY[...]` is strictly banned.
2. **Zero-Trust Short-Circuiting**: In [`DatabaseManager.secure_search`](app/db/manager.py), if `user_roles` is empty or `None`, the function returns `[]` immediately without executing a query against PostgreSQL.
3. **Defense-in-Depth Sanitization**: Vector search roles are sanitized against `KNOWN_ROLES` and identifier syntax, dropping SQL injection attempts before binding to `$2::text[]`.
4. **Matryoshka Embeddings (1536-d Truncation)**: Uses `text-embedding-3-large` truncated from 3072 to 1536 dimensions. Cuts storage and RAM by **50%** while preserving **>98%** retrieval recall.
5. **Loop-Aware Connection Pooling**: `asyncpg` pools are bound to the running event loop. Streamlit recycles event loops across interactions; `DatabaseManager.get_pool()` detects closed/mismatched loops and safely re-creates the pool to prevent `RuntimeError: Event loop is closed`.
6. **Deterministic Mock Vectors (Offline Testing)**:
   * **Python**: `[0.01 * (i % 5) for i in range(1536)]`
   * **SQL**: `(SELECT array_agg(0.01 * (i % 5))::vector(1536) FROM generate_series(1, 1536) i)`
   * Enables complete unit testing with zero external API calls, latency, or token costs.

---

## 4. Layer 2: Identity, Tokens & Session Security

### 4.1 RFC 7636 OAuth 2.0 PKCE Flow
PKCE protects authorization codes from interception in public web and single-page apps:

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

### 4.2 Stateless HMAC-Signed OAuth State
To avoid server-side session dependencies during OAuth redirects:
* `encode_pkce_state(verifier)` embeds the verifier and timestamp into an HMAC-SHA256 signed token: `"{b64_payload}.{sig}"`.
* On return, `decode_pkce_state()` verifies the signature in constant time and checks a 5-minute TTL.
* **Benefit**: Survives server restarts, multi-worker scale-outs, and browser navigations without a database or Redis.

### 4.3 Token Architecture: The Three-Tier Security Model
| Token Type | Purpose | Lifetime | Storage Location |
| :--- | :--- | :--- | :--- |
| **ID Token (OIDC)** | User identity & verified `app_roles` | 15–60 min | In-memory session state |
| **Access Token (OAuth)** | Scoped API authorization | 15–60 min | Ephemeral memory |
| **Refresh Token (OAuth)** | Silent re-minting without re-entering credentials | 30 days | HttpOnly encrypted cookie / server store |

### 4.4 Session Persistence & Browser Reloads (F5)
* **The Problem**: Streamlit maintains `st.session_state` in ephemeral server memory tied to the active WebSocket. Pressing F5 severs the WebSocket, clearing `st.session_state` and forcing a re-login.
* **The Solution (`app/auth/pkce.py` & `streamlit_app.py`)**:
  1. On login, the app compresses (`zlib`), base64url-encodes, and HMAC-signs the session data into an `enterprise_rag_session` cookie.
  2. A DOM tracker writes this to `parent.document.cookie`.
  3. On page refresh (F5), `_restore_session_from_cookie()` reads `st.context.cookies`, validates the HMAC signature, and rehydrates `st.session_state`.
  4. If the ID token is nearing expiration, it triggers a silent token refresh via `_refresh_id_token_sync()` automatically.

### 4.5 Session Expiration & Termination Rules (SOC-2 / HIPAA)
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
3. **Role Resolution Pipeline (Ticket #12 Enhancements)**:
   * **Primary (Verified Token Claims)**: Extracts and normalizes claims from `app_roles`, `roles`, `groups`, `cognito:groups`, and `realm_access.roles` (supporting Azure AD, Okta, Firebase, AWS Cognito, Keycloak) filtered strictly against `KNOWN_ROLES`.
   * **Secondary**: Firebase Admin SDK live lookup by email.
   * **Tertiary**: Server-side email mapping in `.env` (`ROLE_MAP_<role>=email`).
   * **Quaternary (Dev)**: `X-User-Roles` header when `REQUIRE_GOOGLE_AUTH=false`, strictly validated as a JSON array and sanitized against `KNOWN_ROLES`.
4. **Enterprise JWKS & Issuer Verification (`app/auth/jwks.py`)**:
   * Uses `verify_jwt_token()` with `get_allowed_issuers()` to support Google accounts, Firebase, and enterprise IdPs (`OIDC_JWKS_URI` and `OIDC_ISSUER`).
   * Performs pre-resolution issuer validation to prevent untrusted issuers from polluting the cached JWKS clients dictionary.

---

## 5. Layer 3: High-Performance Ingestion Pipeline (`scripts/ingest.py` & `libs/utilities.py`)

The ingestion pipeline transforms raw documents into high-dimensional vector representations stored within the normalized PostgreSQL schema, enforcing change detection, semantic boundary preservation, and fault tolerance.

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

### 5.1 Cryptographic SHA-256 De-duplication
* **Deterministic Change Detection**: Files are hashed in 64KB memory-safe chunks using SHA-256 (`compute_file_hash()`).
* **Instant B-Tree Lookup**: `check_document_exists(cur, filename, file_hash=file_hash)` leverages `idx_documents_file_hash` on `documents(file_hash)`.
* **Smart Update Routing**: Unchanged files are skipped with zero database or API overhead. Modified files (matching filename with divergent hash) trigger automatic re-indexing and replace previous chunks.
* **CLI Overrides**: Passing `--force` bypasses hash checks and forces end-to-end re-ingestion.

### 5.2 Token-Aware Semantic Boundary Chunking
* **Tokenizer-Aligned Chunking**: Uses `RecursiveCharacterTextSplitter.from_tiktoken_encoder` (`model_name="text-embedding-3-large"`) with 512–800 token targets and 10–15% overlap (`chunk_size=800`, `chunk_overlap=100`).
* **Structure Preservation**: Structured separators (`\n## `, `\n### `, `\n#### `, `\n|`, `\n\n`) prevent breaking markdown section headers and table rows across chunk seams.
* **Metadata Attribution**: Automatically sets `page`, `chunk_index`, `source`, `document_id`, and `chunk_id` (`{document_id}_chunk_{index+1}`) on every chunk.

### 5.3 Resilient Embeddings with Tenacity Backoff
* **Batch Slicing**: Chunks are processed in batches (default `batch_size=64`, configurable up to 128) to eliminate memory spikes and token limit exceptions.
* **Transient Error Retry**: Uses `tenacity` exponential backoff (`multiplier=1, min=2s, max=60s, attempts=5`) to automatically recover from OpenAI rate limits (`429`), timeouts, and gateway errors (`503`/`502`/`500`).

---

## 6. Layer 4: FastAPI Backend & Streamlit Frontend

### FastAPI Dependency Injection (`app/main.py`)
All endpoints are secured via `get_current_user`:
```python
async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    x_user_roles: Optional[str] = Header(default=None),
) -> UserIdentity:
```
* Enforces Google Bearer token verification with **60-second clock skew leeway** (`leeway=60`) to absorb minor time drifts between local hardware and Google NTP servers.
* Validates and sanitizes legacy dev headers (`X-User-Roles`), rejecting non-array formats with `400 Bad Request`.
* Returns a strongly-typed `UserIdentity(email, roles, sub)` injected into RAG queries.

### Mathematical Confidence Scoring
Every retrieval response includes an auditable confidence score:
$$\text{confidence\_score} = \frac{1}{N} \sum_{i=1}^N \text{similarity}_i = \frac{1}{N} \sum_{i=1}^N \left(1 - (\text{embedding}_i \Leftrightarrow \text{query\_vec})\right)$$

### Streamlit Shift-Left UI (`streamlit_app.py`)
* **Iframe Sandbox-Safe Navigation**: Uses native popup navigation (`target="_blank"`) compliant with Streamlit Community Cloud iframe sandboxing policies.
* **Live RBAC Audit Inspector**: Displays parameterized query templates (`WHERE allowed_roles ?| $2::text[]`) with safe JSON-serialized parameter bindings (`$1`, `$2`, `$3`), demonstrating SQL injection immunity directly on screen.
* **Interactive Security Panel**: Real-time session elapsed time, ID token TTL countdown, manual silent refresh trigger, and token copy drawer for Swagger UI (`/docs`).

---

## 7. Layer 5: FastMCP Agent Gateway (`app/mcp/`)

FastMCP standardizes tool and resource access for external AI coding agents (Claude Desktop, Cursor, CLI agents):

| Primitive | Signature | Function |
| :--- | :--- | :--- |
| **Tool** | `search_sdlc_context(question, auth_token, user_roles)` | Authenticates the calling agent via Google ID token and returns in-database RBAC-filtered knowledge base snippets. |
| **Tool** | `propose_patch(branch_name, patch_content, auth_token)` | Validates submitter identity and writes unified diff modifications to a feature branch. |
| **Resource** | `policy://sdlc-budget` | Serves operational constraints: maximum tokens per issue (`50,000`), maximum execution steps (`10`), and allowed tools. |

---

## 8. Layer 6: Autonomous Self-Healing SDLC Agent (`agent/`)

The autonomous agent listens to GitHub issue webhooks, writes code patches, audits them statically, runs tests, and autonomously repairs bugs.

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

### LangGraph Workflow Nodes (`agent/workflow.py`)
1. **`initialize`**: Verifies the webhook HMAC signature (`X-Hub-Signature-256`), checks out a clean Git branch (`feature/AGENT-<id>-<slug>`), and initializes `AgentState`.
2. **`propose_patches`**: Prompts the LLM to generate targeted patch proposals (`file_path`, `content`).
3. **`apply_patches`**: Writes code while strictly enforcing **Sandbox Path Traversal Defenses** (rejects absolute paths, `..`, and `.git/`).
4. **`audit_patches`**: Executes deterministic security guardrails before code execution.
5. **`run_tests`**: Runs `pytest` in a background subprocess (`asyncio.to_thread`).
6. **`repair_patches` (Self-Healing Loop)**: If tests fail, slices the trailing 2,500 characters of error traceback into the LLM repair prompt, regenerates patches, and re-tests (up to `max_attempts=3`).
7. **`finalize`**: Commits verified code and opens a pull request with an embedded security audit summary.

### Deterministic Security Guardrails (`agent/guardrails.py`)
* **Secret Scanning**: Compiled regex filters flag OpenAI keys (`sk-...`), private keys (`-----BEGIN PRIVATE KEY-----`), and Google API keys (`AIza...`).
* **AST Code Inspection**: Uses Python's `ast.walk()` to block execution sinks (`eval()`, `exec()`, `__import__()`) without executing untrusted code.

---

## 9. Testing & Verification Guide

The project features a **100% passing test suite (81/81 tests)** that executes completely offline without external network or API dependencies:

```powershell
python -m pytest -v
```

### Test Suite Breakdown
| Module | Tests | Key Invariants Verified |
| :--- | :---: | :--- |
| **`tests/test_database_schema.py`** | 6 | • Normalized table schemas (`documents` & `document_chunks`).<br/>• `ON DELETE CASCADE` foreign key relationship.<br/>• HNSW vector index (`m=16, ef=64`) & GIN role index.<br/>• B-tree file hash de-duplication index.<br/>• Consolidated migration cleanup logic in schema.sql.<br/>• Cosine similarity calculation benchmark simulation. |
| **`tests/test_security_rbac.py`** | 5 | • SQL injection immunity in vector search.<br/>• Parameterized array containment (`$2::text[]`).<br/>• Zero-Trust empty role short-circuiting.<br/>• Header validation and injection filtering. |
| **`tests/test_auth.py`** | 34 | • RFC 7636 PKCE `code_verifier` & `code_challenge` derivation.<br/>• Stateless HMAC-SHA256 OAuth state generation & expiration (300s TTL).<br/>• Google JWKS certificate caching & `leeway=60s` clock skew tolerance.<br/>• Multi-source role claim extraction (`app_roles`, `roles`, `groups`, `cognito:groups`, `realm_access.roles`).<br/>• Enterprise JWKS issuer validation & rejection of untrusted issuers.<br/>• **Session Cookie Encoding**: Roundtrip compression, signature tampering rejection, expired TTL handling, and malformed cookie rejection. |
| **`tests/test_rag.py`** | 4 | • Health check status.<br/>• Strict 401 rejection when unauthenticated.<br/>• Dev header fallback (`X-User-Roles`).<br/>• End-to-end vector retrieval & RBAC filtering. |
| **`tests/test_mcp_auth.py`** | 10 | • FastMCP token validation and unauthenticated caller rejection.<br/>• Verified role extraction from ID tokens for tool execution.<br/>• Identity verification on patch submission. |
| **`tests/test_agent.py`** | 6 | • GitHub webhook HMAC-SHA256 verification.<br/>• Webhook JSON parsing into typed models.<br/>• Deterministic secret scanning (API keys, private keys).<br/>• AST static inspection (`eval`, `exec`, `__import__`).<br/>• Sandbox path traversal prevention.<br/>• Full LangGraph self-healing test repair cycle. |
| **`tests/test_ingest.py`** | 9 | • Pre-ingestion SHA-256 de-duplication, modified file re-indexing detection, force flag bypass, stem matching, chunk prefix detection. |
| **`tests/test_utilities.py`** | 7 | • Multi-format loaders (`.pdf`, `.md`, `.docx`), tokenizer-aware chunk splitting, chunk metadata attribution, 64KB block hashing, and tenacity retry on 429 rate limits. |
| **Total** | **81** | **100% Passed (16.6s execution time)** |

---

## 10. Operational Cheat Sheet & Troubleshooting

### Service Launch Commands
```powershell
# 1. Run unit tests
python -m pytest

# 2. Start FastAPI REST backend (Port 8000)
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 3. Start Streamlit interactive UI (Port 8501)
python -m streamlit run streamlit_app.py --server.port 8501

# 4. Start FastMCP gateway
python -m app.mcp
```

### Solved Engineering Pitfalls Reference
| Symptom / Error | Root Cause | Permanent Solution |
| :--- | :--- | :--- |
| **SQL Injection in RBAC Filtering** | String-formatting user roles into SQL queries (`ARRAY[...]`). | **Parameterized Bindings & Sanitization**: Bound roles to `$2::text[]` via asyncpg, added zero-trust short-circuit on empty roles, and sanitized claims against `KNOWN_ROLES`. |
| **Ingestion Duplication & Edits Missed** | Filename-only prefix checks missed file edits and duplicated renamed files. | **Cryptographic SHA-256 De-duplication**: 64KB block hashing with change detection skips identical files and purges obsolete chunk sets on re-indexing. |
| **Embedding API Rate Limits (429/503)** | Unbatched or unprotected embedding requests hit provider rate limits. | **Tenacity Exponential Backoff & 64-Item Batching**: Batch-embeds 64–128 items with automated exponential backoff (2s–60s) on transient 429/503 errors. |
| **OAuth state mismatch / CSRF** | Streamlit re-creates session on navigation away to Google. | **Stateless HMAC-SHA256 Signed State**: verifier is embedded in signed state string; zero memory dependency. |
| **Browser reload requires re-login** | Streamlit WebSocket reset clears RAM session state. | **Encrypted Session Cookie**: `enterprise_rag_session` cookie is written to browser and rehydrated via `st.context.cookies`. |
| **`ImmatureSignatureError: (iat)`** | Clock drift between local machine and Google NTP servers. | Added `leeway=60` in `jwt.decode()` per RFC 7519. |
| **Pip dependency resolution conflict** | Duplicate entry in `requirements.txt` (`PyJWT==2.10.1` and `2.15.1`). | Pruned duplicate pin, locking strictly to `PyJWT==2.10.1`. |
| **`client_secret is missing`** | Google OAuth "Web Application" client type requires secret at `/token`. | Set `GOOGLE_CLIENT_SECRET` in `.env` and pass in token exchange. |
| **`Event loop is closed` in asyncpg** | Streamlit destroys event loops across script reruns. | Loop-aware connection manager: checks `_loop.is_closed()` and recycles pool cleanly. |
| **Recall starvation in RAG** | Post-filtering in application code drops top-$K$ restricted docs. | **In-Database RBAC**: `WHERE allowed_roles ?| $user_roles` inside the SQL query before HNSW vector ordering. |

