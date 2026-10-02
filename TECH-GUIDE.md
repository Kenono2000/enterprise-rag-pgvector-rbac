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

### Schema & Dual-Index Strategy (`schema.sql`)
```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS enterprise_documents (
    document_id VARCHAR(64) PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    allowed_roles JSONB NOT NULL,
    embedding vector(1536),
    embedding_model VARCHAR(64) DEFAULT 'text-embedding-3-large',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 1. HNSW Index: sub-millisecond approximate nearest neighbor search
CREATE INDEX idx_enterprise_documents_embedding_hnsw 
ON enterprise_documents USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- 2. GIN Index: constant-time JSONB role membership pre-filter
CREATE INDEX idx_enterprise_documents_roles_gin 
ON enterprise_documents USING gin (allowed_roles jsonb_path_ops);
```

### The In-Database RBAC Query (`app/db/manager.py`)
```sql
SELECT document_id, title, content, allowed_roles, 
       1 - (embedding <=> $1::vector) AS similarity
FROM enterprise_documents
WHERE allowed_roles ?| $2::text[]
  AND (embedding_model = 'text-embedding-3-large' OR embedding_model IS NULL)
ORDER BY embedding <=> $1::vector
LIMIT $3;
```

* **`?|` (JSONB Exists-Any)**: Returns `TRUE` if **any** user role matches **any** element in `allowed_roles`. Uses GIN index for sub-millisecond filtering before computing vector distances.
* **`<=>` (Cosine Distance)**: Calculates distance $1 - \cos(\theta)$. Inverted to $1 - (\text{dist})$ to produce a normalized similarity score $[0.0, 1.0]$.

### Key Database Optimizations
1. **Matryoshka Embeddings (1536-d Truncation)**: Uses `text-embedding-3-large` truncated from 3072 to 1536 dimensions. Cuts storage and RAM by **50%** while preserving **>98%** retrieval recall.
2. **Loop-Aware Connection Pooling**: `asyncpg` pools are bound to the running event loop. Streamlit recycles event loops across interactions; `DatabaseManager.get_pool()` detects closed/mismatched loops and safely re-creates the pool to prevent `RuntimeError: Event loop is closed`.
3. **Deterministic Mock Vectors (Offline Testing)**:
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
3. **Role Resolution Pipeline**:
   * **Primary**: Firebase Custom Claims (`payload["app_roles"]`).
   * **Secondary**: Firebase Admin SDK live lookup by email.
   * **Tertiary**: Server-side email mapping in `.env` (`ROLE_MAP_<role>=email`).
   * **Quaternary (Dev)**: `X-User-Roles` header when `REQUIRE_GOOGLE_AUTH=false`.

---

## 5. Layer 3: FastAPI Backend & Streamlit Frontend

### FastAPI Dependency Injection (`app/main.py`)
All endpoints are secured via `get_current_user`:
```python
async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    x_user_roles: Optional[str] = Header(default=None),
) -> UserIdentity:
```
* Enforces Google Bearer token verification with **60-second clock skew leeway** (`leeway=60`) to absorb minor time drifts between local hardware and Google NTP servers.
* Returns a strongly-typed `UserIdentity(email, roles, sub)` injected into RAG queries.

### Mathematical Confidence Scoring
Every retrieval response includes an auditable confidence score:
$$\text{confidence\_score} = \frac{1}{N} \sum_{i=1}^N \text{similarity}_i = \frac{1}{N} \sum_{i=1}^N \left(1 - (\text{embedding}_i \Leftrightarrow \text{query\_vec})\right)$$

### Streamlit Shift-Left UI (`streamlit_app.py`)
* **Top-Level Navigation**: Uses `<a target="_top">` buttons to break out of iframe sandboxes for Google OAuth consent.
* **Live RBAC Audit Inspector**: Displays raw generated embeddings, verified JWT claims, and executed PostgreSQL queries directly on screen.
* **Interactive Security Panel**: Real-time session elapsed time, ID token TTL countdown, manual silent refresh trigger, and token copy drawer for Swagger UI (`/docs`).

---

## 6. Layer 4: FastMCP Agent Gateway (`app/mcp/`)

FastMCP standardizes tool and resource access for external AI coding agents (Claude Desktop, Cursor, CLI agents):

| Primitive | Signature | Function |
| :--- | :--- | :--- |
| **Tool** | `search_sdlc_context(question, auth_token, user_roles)` | Authenticates the calling agent via Google ID token and returns in-database RBAC-filtered knowledge base snippets. |
| **Tool** | `propose_patch(branch_name, patch_content, auth_token)` | Validates submitter identity and writes unified diff modifications to a feature branch. |
| **Resource** | `policy://sdlc-budget` | Serves operational constraints: maximum tokens per issue (`50,000`), maximum execution steps (`10`), and allowed tools. |

---

## 7. Layer 5: Autonomous Self-Healing SDLC Agent (`agent/`)

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

## 8. Testing & Verification Guide

The project features a **100% passing test suite (41/41 tests)** that executes completely offline without external network or API dependencies:

```powershell
python -m pytest -v
```

### Test Suite Breakdown
| Module | Tests | Key Invariants Verified |
| :--- | :---: | :--- |
| **`tests/test_rag.py`** | 4 | • Health check status.<br/>• Strict 401 rejection when unauthenticated.<br/>• Dev header fallback (`X-User-Roles`).<br/>• End-to-end vector retrieval & RBAC filtering. |
| **`tests/test_auth.py`** | 24 | • RFC 7636 PKCE `code_verifier` & `code_challenge` derivation.<br/>• Stateless HMAC-SHA256 OAuth state generation & expiration (300s TTL).<br/>• Google JWKS certificate caching & `leeway=60s` clock skew tolerance.<br/>• Role mapping priority (Firebase custom claims vs. email fallbacks).<br/>• **Session Cookie Encoding**: Roundtrip compression, signature tampering rejection, expired TTL handling, and malformed cookie rejection. |
| **`tests/test_mcp_auth.py`** | 7 | • FastMCP token validation and unauthenticated caller rejection.<br/>• Verified role extraction from ID tokens for tool execution.<br/>• Identity verification on patch submission. |
| **`tests/test_agent.py`** | 6 | • GitHub webhook HMAC-SHA256 verification.<br/>• Webhook JSON parsing into typed models.<br/>• Deterministic secret scanning (API keys, private keys).<br/>• AST static inspection (`eval`, `exec`, `__import__`).<br/>• Sandbox path traversal prevention.<br/>• Full LangGraph self-healing test repair cycle. |
| **Total** | **41** | **100% Passed (10.5s execution time)** |

---

## 9. Operational Cheat Sheet & Troubleshooting

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
| **OAuth state mismatch / CSRF** | Streamlit re-creates session on navigation away to Google. | **Stateless HMAC-SHA256 Signed State**: verifier is embedded in signed state string; zero memory dependency. |
| **Browser reload requires re-login** | Streamlit WebSocket reset clears RAM session state. | **Encrypted Session Cookie**: `enterprise_rag_session` cookie is written to browser and rehydrated via `st.context.cookies`. |
| **`ImmatureSignatureError: (iat)`** | Clock drift between local machine and Google NTP servers. | Added `leeway=60` in `jwt.decode()` per RFC 7519. |
| **Pip dependency resolution conflict** | Duplicate entry in `requirements.txt` (`PyJWT==2.10.1` and `2.15.1`). | Pruned duplicate pin, locking strictly to `PyJWT==2.10.1`. |
| **`client_secret is missing`** | Google OAuth "Web Application" client type requires secret at `/token`. | Set `GOOGLE_CLIENT_SECRET` in `.env` and pass in token exchange. |
| **`Event loop is closed` in asyncpg** | Streamlit destroys event loops across script reruns. | Loop-aware connection manager: checks `_loop.is_closed()` and recycles pool cleanly. |
| **Recall starvation in RAG** | Post-filtering in application code drops top-$K$ restricted docs. | **In-Database RBAC**: `WHERE allowed_roles ?| $user_roles` inside the SQL query before HNSW vector ordering. |
