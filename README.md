# 🛡️ Enterprise Zero-Trust RAG Microservice & Autonomous SDLC

### 👤 Architect
**[Ken Wong](https://www.linkedin.com/in/kenwong-architect/)**  
*Target stack: Python 3.11+, PostgreSQL 16 + pgvector, FastAPI, Streamlit, Google OAuth 2.0 PKCE, Google JWKS, Firebase Identity, FastMCP, LangGraph*

---

## 🚀 Live Architecture Artifacts

| Component | Description | Access Link |
| :--- | :--- | :--- |
| **Visual UI** | Shift-Left In-Database RBAC Demo (Streamlit) | [enterprise-rag-pgvector-rbac.streamlit.app](https://enterprise-rag-pgvector-rbac.streamlit.app) |
| **API Docs** | Live OpenAPI / Interactive Swagger UI | [enterprise-rag-api-ksez.onrender.com/docs](https://enterprise-rag-api-ksez.onrender.com/docs) |
| **Repository** | Auditable Source Code & Test Suite | [github.com/Kenono2000/enterprise-rag-pgvector-rbac](https://github.com/Kenono2000/enterprise-rag-pgvector-rbac) |
| **Technical Guide** | In-Depth Architecture & Implementation Manual | [`project_technical_guide.md`](project_technical_guide.md) |

---

## 📑 Table of Contents
1. [Executive Summary & Core Value Proposition](#1-executive-summary--core-value-proposition)
2. [End-to-End System Architecture](#2-end-to-end-system-architecture)
3. [Architectural Philosophy: Standard RAG vs. Zero-Trust In-Database RBAC](#3-architectural-philosophy-standard-rag-vs-zero-trust-in-database-rbac)
4. [Consolidated Codebase Structure](#4-consolidated-codebase-structure)
5. [Layer 1: Database & pgvector Indexing (`schema.sql` & `app/db/`)](#5-layer-1-database--pgvector-indexing-schemasql--appdb)
6. [Layer 2: Identity & Cryptographic Security (`app/auth/`)](#6-layer-2-identity--cryptographic-security-appauth)
   - [6.1 RFC 7636 OAuth 2.0 PKCE Flow](#61-rfc-7636-oauth-20-pkce-flow)
   - [6.2 Stateless HMAC-Signed OAuth State](#62-stateless-hmac-signed-oauth-state)
   - [6.3 Google Public JWKS Verification & Clock Skew Leeway](#63-google-public-jwks-verification--clock-skew-leeway)
   - [6.4 Role Storage in Tokens & Resolution Pipeline](#64-role-storage-in-tokens--resolution-pipeline)
   - [6.5 Enterprise Custom Role Provisioning](#65-enterprise-custom-role-provisioning)
7. [Layer 3: API & Interactive Frontend (`app/main.py` & `streamlit_app.py`)](#7-layer-3-api--interactive-frontend-appmainpy--streamlit_apppy)
8. [Layer 4: Model Context Protocol Gateway (`app/mcp.py`)](#8-layer-4-model-context-protocol-gateway-appmcppy)
9. [Layer 5: Autonomous SDLC Agent (`agent/`)](#9-layer-5-autonomous-sdlc-agent-agent)
10. [Troubleshooting & Solved Engineering Challenges](#10-troubleshooting--solved-engineering-challenges)
11. [Environment Configuration Reference (`.env`)](#11-environment-configuration-reference-env)
12. [Application Execution & Verification Guide](#12-application-execution--verification-guide)
13. [Key Engineering Takeaways](#13-key-engineering-takeaways)

---

## 1. Executive Summary & Core Value Proposition

Standard enterprise RAG systems frequently suffer from **context eviction**, **recall starvation**, and **process memory leaks** due to post-retrieval authorization filtering.

This project delivers an enterprise-grade, end-to-end reference implementation demonstrating:
1. **Zero-Trust In-Database RBAC**: Filtering rows directly in the PostgreSQL kernel (`allowed_roles ?| $user_roles`) prior to vector similarity scoring, ensuring unauthorized data never crosses into application memory or LLM contexts.
2. **Sub-Millisecond Vector Search**: Combining `pgvector` HNSW indexing with GIN JSONB path indexes over dense 1536-dimensional embeddings.
3. **Stateless Google OAuth 2.0 PKCE**: A zero-memory HMAC-SHA256 signed state mechanism that survives browser redirects and server restarts.
4. **Governed FastMCP Gateway**: Identity-aware Model Context Protocol tools for external AI agents (e.g. Cursor, Claude Desktop).
5. **Autonomous Self-Healing SDLC Agent**: A LangGraph state machine with deterministic AST security inspection and closed-loop test error repair.

---

## 2. End-to-End System Architecture

```mermaid
flowchart TB
    subgraph Client ["Client & Consumer Layer"]
        browser["User Browser / Streamlit UI<br/>(localhost:8501)"]
        mcp_client["AI Agent / FastMCP Client"]
    end

    subgraph Identity ["Cryptographic Security & Identity"]
        google["Google Accounts (OAuth 2.0 PKCE)<br/>accounts.google.com"]
        jwks["Google Public JWKS (RS256)<br/>certs with leeway=60s"]
        firebase["Firebase Identity Platform<br/>Custom Claims: app_roles"]
    end

    subgraph Microservice ["FastAPI Zero-Trust Core (app/)"]
        api["API Gateway (POST /api/v1/query)<br/>Dependency: get_current_user"]
        embed["Embedding Engine<br/>text-embedding-3-large (1536-d)"]
        pool["Loop-Aware asyncpg Pool"]
    end

    subgraph Data ["Data Layer (PostgreSQL 16)"]
        db[("enterprise_documents<br/>• GIN: allowed_roles jsonb_path_ops<br/>• HNSW: embedding vector_cosine_ops")]
    end

    subgraph SDLC ["Autonomous SDLC Agent (agent/)"]
        langgraph["LangGraph State Machine<br/>propose ➔ apply ➔ audit ➔ test ➔ repair"]
        guardrails["PolicyEngine<br/>Deterministic AST + Secret Scanner"]
    end

    browser -->|1. PKCE Auth Code| google
    google -->|2. RS256 ID Token| browser
    browser -->|3. Bearer Token Query| api
    api -->|4. Verify Signature & Leeway| jwks
    api -->|5. Extract Roles / Claims| firebase
    api -->|6. Generate Embedding| embed
    api -->|7. In-Database RBAC SQL| pool
    pool -->|8. Cosine Distance + JSONB Filter| db
    db -->|9. Authorized Top-K Only| api
    api -->|10. Grounded Response + Citations| browser

    mcp_client -->|Governed Tool Call| api
    SDLC -->|Context Hydration| api

    style db fill:#f9f,stroke:#333,stroke-width:2px
    style Identity fill:#dfd,stroke:#333,stroke-width:2px
    style Microservice fill:#f0f8ff,stroke:#007acc,stroke-dasharray: 5 5
    style SDLC fill:#fff9c4,stroke:#fbc02d,stroke-width:2px
```

---

## 3. Architectural Philosophy: Standard RAG vs. Zero-Trust In-Database RBAC

### The Flaw in Post-Filtering RAG
In traditional RAG systems, access control is applied **after** vector retrieval:

```text
[User Query] ──► [Vector DB: Retrieve Top-K] ──► [Python App Filters by Role] ──► [LLM Context]
                                                        │
                                                        └─► Context Eviction & Leakage
```

This design introduces two critical vulnerabilities:
1. **Context Eviction / Recall Starvation**: If an unauthorized user queries for financial documents, and the top-$K$ most semantically relevant documents belong to restricted executive tiers, application-level filtering removes all $K$ documents. The user receives 0 results, even if relevant tier-appropriate documents existed at rank $K+1$ through $2K$.
2. **Process Memory Leaks & Prompt Injection**: Sensitive documents are retrieved into application heap memory before filtering. Unredacted text enters heap caches, logs, and process memory, leaving confidential data exposed to prompt injection or crash dump leaks.

### The Zero-Trust Guarantee
In this architecture, role-based access control is evaluated **directly inside the database engine**:

```text
[User Query] ──► [Verified JWT] ──► [Extract Roles] ──► [PostgreSQL Engine] ──► [LLM Context]
                                                               │
                                  ┌────────────────────────────┴───────────────────────────┐
                                  │ WHERE allowed_roles ?| $user_roles (GIN Index Filter) │
                                  │ ORDER BY embedding <=> $query_vec  (HNSW Index Scan)  │
                                  └────────────────────────────────────────────────────────┘
```

- Unauthorized documents are **never read from disk into the database buffer cache**, **never transmitted across the network TLS socket**, and **never loaded into Python heap memory**.
- The pgvector HNSW index ranks *only* the documents that the user is cryptographically authorized to see.

---

## 4. Consolidated Codebase Structure

```text
enterprise-rag-pgvector-rbac/
├── app/                        # 🛡️ Core Zero-Trust RAG Microservice
│   ├── __init__.py
│   ├── main.py                 # Primary FastAPI entry point (/api/v1/query, /health)
│   ├── auth/                   # Consolidated Auth (PKCE, Google JWKS, Role Mapper)
│   │   ├── jwks.py             # RS256 JWKS verification with leeway=60s
│   │   ├── pkce.py             # PKCE RFC 7636 + stateless HMAC signed state
│   │   └── role_mapper.py      # Firebase claims & email fallback role mapping
│   ├── db/                     # Consolidated Database & AI Services
│   │   ├── manager.py          # asyncpg connection pool + Zero-Trust RBAC SQL search
│   │   └── llm.py              # OpenAI text-embedding-3-large & completions + local mock
│   └── mcp.py                  # FastMCP Gateway with Google OAuth auth_token
│
├── agent/                      # 🤖 Autonomous SDLC Agent (Isolated from Core RAG)
│   ├── __init__.py
│   ├── workflow.py             # LangGraph state machine (patch, audit, test, PR)
│   ├── guardrails.py           # Deterministic AST & secret security inspection
│   └── parser.py               # GitHub webhook parser & HMAC-SHA256 signature verifier
│
├── scripts/                    # 🛠️ Administrative & Operational Tooling
│   └── set_user_roles.py       # Firebase custom claims CLI management script
│
├── tests/                      # 🧪 Consolidated 100% Passing Test Suite (37 tests)
│   ├── test_rag.py             # FastAPI endpoints & Zero-Trust RBAC tests
│   ├── test_auth.py            # PKCE & Google JWKS token tests
│   ├── test_mcp_auth.py        # FastMCP OAuth auth_token verification tests
│   └── test_agent.py           # SDLC LangGraph workflow & guardrails tests
│
├── streamlit_app.py            # 🖥️ Interactive Demo UI (PKCE Sign-In + Live Search)
├── main.py                     # Root entry point -> runs app.main:app
├── docker-compose.yml          # PostgreSQL + pgvector container
├── requirements.txt            # Pinned production dependencies
├── schema.sql                  # Database schema + seed document embeddings
└── project_technical_guide.md  # Deep-dive architecture and troubleshooting manual
```

---

## 5. Layer 1: Database & pgvector Indexing (`schema.sql` & `app/db/`)

### Schema & Indexing (`schema.sql`)
```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS enterprise_documents (
    document_id VARCHAR(64) PRIMARY KEY,
    title VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    allowed_roles JSONB NOT NULL,
    embedding vector(1536),
    embedding_model VARCHAR(64) DEFAULT 'text-embedding-3-large',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- 1. HNSW Index for sub-millisecond approximate nearest neighbor search
CREATE INDEX IF NOT EXISTS idx_enterprise_documents_embedding_hnsw 
ON enterprise_documents 
USING hnsw (embedding vector_cosine_ops)
WITH (m = 16, ef_construction = 64);

-- 2. GIN Index for constant-time JSONB role membership checks
CREATE INDEX IF NOT EXISTS idx_enterprise_documents_roles_gin 
ON enterprise_documents 
USING gin (allowed_roles jsonb_path_ops);
```

### The In-Database RBAC SQL Query (`app/db/manager.py`)
```sql
SELECT document_id, title, content, allowed_roles, 
       1 - (embedding <=> $1::vector) AS similarity
FROM enterprise_documents
WHERE allowed_roles ?| $2::text[]
  AND (embedding_model = 'text-embedding-3-large' OR embedding_model IS NULL)
ORDER BY embedding <=> $1::vector
LIMIT $3;
```

#### SQL Operator Semantics:
- **`?|` (JSONB "Exists Any" Operator)**: Evaluates a JSONB array on the left against a text array on the right (`$2::text[]`). Returns `TRUE` if **any** role matches **any** allowed role.
- **`<=>` (Vector Cosine Distance)**: Calculates $1 - \cos(\theta)$ between the document embedding and query vector `$1`.
- **`1 - (embedding <=> $1::vector)`**: Inverts distance into a normalized similarity score $[0.0, 1.0]$.

### Loop-Aware Connection Pooling
`asyncpg` connection pools are bound to the specific `asyncio` event loop active at creation time. While FastAPI runs on a single persistent loop, Streamlit creates and tears down a new event loop on every interaction. `DatabaseManager.get_pool()` detects loop changes or closed loops, safely recycling the pool to prevent `RuntimeError: Event loop is closed`.

---

## 6. Layer 2: Identity & Cryptographic Security (`app/auth/`)

### 6.1 RFC 7636 OAuth 2.0 PKCE Flow

```mermaid
sequenceDiagram
    autonumber
    actor User as User Browser / Streamlit
    participant Google as accounts.google.com
    participant API as FastAPI Gateway (app/main.py)
    participant JWKS as Google Public JWKS

    User->>User: generate_code_verifier() & derive_code_challenge()
    User->>User: encode_pkce_state(verifier) [HMAC-SHA256 Signed]
    User->>Google: Redirect with code_challenge & signed state
    Google->>User: Renders Consent Screen
    User->>Google: Approves Login
    Google->>User: Redirects to localhost:8501/?code=XXX&state=YYY
    User->>User: decode_pkce_state(state) -> verifies HMAC & extracts verifier
    User->>Google: POST /token (code, verifier, client_id, client_secret)
    Google->>User: Returns {id_token, access_token}
    User->>API: Calls /api/v1/query with Bearer <id_token>
    API->>JWKS: Fetches Google Public Certs (RS256)
    API->>API: Validates signature, audience, exp, leeway=60s
    API->>API: extract_roles(payload) -> ['finance_executive', ...]
```

### 6.2 Stateless HMAC-Signed OAuth State
Traditional OAuth implementations store `state -> code_verifier` in memory or in a server session. In Streamlit or serverless architectures, navigating the browser away to Google wipes the in-memory session, causing `"OAuth state mismatch — possible CSRF"`.

**Our Solution**: Stateless Signed OAuth State (`app/auth/pkce.py`):
```python
def encode_pkce_state(code_verifier: str, nonce: Optional[str] = None) -> str:
    payload = {"v": code_verifier, "t": int(time.time()), "n": nonce or secrets.token_hex(8)}
    b64_data = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    sig = hmac.new(_get_hmac_secret(), b64_data.encode(), hashlib.sha256).hexdigest()
    return f"{b64_data}.{sig}"
```
- Embedded verifier and timestamp signed with HMAC-SHA256.
- Validated on callback with constant-time `hmac.compare_digest()` and a 5-minute TTL.
- Zero memory footprint; immune to reloads, server restarts, and multi-worker scale-outs.

### 6.3 Google Public JWKS Verification & Clock Skew Leeway
Google ID tokens are signed with RS256. `app/auth/jwks.py` uses `PyJWKClient` to dynamically fetch and cache public signing keys from `https://www.googleapis.com/oauth2/v3/certs`. A configured `leeway=60` absorbs minor NTP clock drift between client machines and Google Cloud servers, eliminating `ImmatureSignatureError: The token is not yet valid (iat)`.

### 6.4 Role Storage in Tokens & Resolution Pipeline

```mermaid
flowchart TD
    Req[Incoming Request] --> AuthMode{REQUIRE_GOOGLE_AUTH?}
    
    AuthMode -->|true: Enforced| A[Incoming Bearer ID Token]
    A --> B[Verify RS256 Signature via JWKS]
    B --> C{"Does payload contain 'app_roles'?"}
    C -->|Yes: Custom Claim| D["Use payload['app_roles'] directly"]
    C -->|No: Standard Token| E["Lookup user custom claims via Firebase Admin SDK"]
    E --> F{"Firebase claims found?"}
    F -->|Yes: app_roles found| G["Use Firebase Admin claims"]
    F -->|No claims| H["Match env vars: ROLE_MAP_role = email"]
    H --> I[Assign matched roles from env]
    
    AuthMode -->|false: Dev Fallback| J{"X-User-Roles header present?"}
    J -->|Yes| K[Parse roles from header]
    J -->|No| L[Default empty roles]
    
    D --> UserIdentity[Construct Authenticated UserIdentity]
    G --> UserIdentity
    I --> UserIdentity
    K --> UserIdentity
    L --> UserIdentity
```

1. **Primary: Custom JWT Claim (`payload["app_roles"]`)**: Embedded by Firebase / GCIP.
2. **Secondary: Firebase Admin SDK Live Lookup (`_get_firebase_claims_by_email`)**: For standard Google OAuth tokens, queries Firebase Auth for user custom claims by email.
3. **Tertiary: Server-Side Email Fallback (`ROLE_MAP_<ROLE>`)**: Matches email against server configuration in `.env`.
4. **Quaternary: Offline Dev Fallback (`X-User-Roles`)**: Enabled strictly when `REQUIRE_GOOGLE_AUTH=false`.

### 6.5 Enterprise Custom Role Provisioning
Custom user claims are assigned via the provided CLI tool:
```powershell
python scripts/set_user_roles.py --email user@example.com --roles engineer finance_executive
```
*(See [`project_technical_guide.md`](project_technical_guide.md#46-implementation-guide-static-role-provisioning-via-admin-sdk) for GCIP `beforeSignIn` blocking Cloud Functions and token refresh lifecycle).*

---

## 7. Layer 3: API & Interactive Frontend (`app/main.py` & `streamlit_app.py`)

- **FastAPI Dependency Injection (`get_current_user`)**: Secures `/api/v1/query`. Unauthenticated callers receive HTTP 401 when `REQUIRE_GOOGLE_AUTH=true`.
- **Streamlit Demo UI (`streamlit_app.py`)**:
  - Implements an iframe breakout button (`target="_top"`) for reliable Google consent screen redirection.
  - Features a **Live RBAC SQL Inspector** displaying decoded JWT claims, generated embeddings, and executed SQL query telemetry in real time.
  - Includes a sidebar token copy box for direct testing in Swagger UI (`/docs`).

---

## 8. Layer 4: Model Context Protocol Gateway (`app/mcp.py`)

Exposes Zero-Trust RAG retrieval to AI agents via FastMCP:
```python
@mcp.tool()
async def search_sdlc_context(
    question: str,
    auth_token: Optional[str] = None,
    user_roles: Optional[list[str]] = None,
) -> str:
```
External agents supply their Google ID token as `auth_token`, ensuring identical in-database RBAC enforcement across both human and agentic interfaces.

---

## 9. Layer 5: Autonomous SDLC Agent (`agent/`)

```mermaid
stateDiagram-v2
    [*] --> initialize : GitHub Issue Webhook
    initialize --> propose_patches : Feature Branch Created
    propose_patches --> apply_patches : Sandbox Path Defense
    apply_patches --> audit_patches : AST & Secret Gate
    
    audit_patches --> run_tests : Security Gate PASSED
    audit_patches --> [*] : Security Gate FAILED (Reject)
    
    run_tests --> finalize : pytest PASSED
    run_tests --> repair_patches : pytest FAILED (Self-Correction)
    run_tests --> [*] : Max Retries Exceeded
    
    repair_patches --> apply_patches
    finalize --> [*] : Git Commit & GitHub PR Opened
```

- **LangGraph State Machine (`agent/workflow.py`)**: Coordinates automated development cycles with automated patch proposing, applying, auditing, testing, and self-healing.
- **Deterministic Guardrails (`agent/guardrails.py`)**:
  - **AST Syntax Inspection**: Uses Python `ast.walk` to block execution sinks (`eval()`, `exec()`, `__import__()`).
  - **Secret Scrubbing**: Regex filters detect exposed API keys, private keys, and cloud credentials before test execution.
- **Closed-Loop Self-Healing**: Captures `pytest` stderr and tracebacks to prompt the LLM for automated patch self-correction (configurable retry limit).

---

## 10. Troubleshooting & Solved Engineering Challenges

| Issue Encountered | Root Cause | Engineering Solution |
| :--- | :--- | :--- |
| **`403 Identity Toolkit disabled`** | API not enabled in GCP project. | Enabled via `gcloud services enable identitytoolkit.googleapis.com`. |
| **`OAuth state mismatch / CSRF`** | Streamlit wipes memory on browser redirect. | Implemented **Stateless HMAC-SHA256 Signed State** with TTL. |
| **Redirect stuck on Google login** | Browser trapped in iframe sandbox. | Renders direct HTML `<a>` tag with `target="_top"`. |
| **`The token is not yet valid (iat)`** | Clock skew between local host and Google servers. | Added `leeway=60` to `jwt.decode()` per RFC 7519. |
| **`client_secret is missing`** | Google OAuth client registered as Web App. | Supplied `GOOGLE_CLIENT_SECRET` at `/token`. |
| **`RuntimeError: Event loop closed`** | `asyncpg` pool tied to dead event loop in Streamlit. | Implemented loop-aware pool recycler in `DatabaseManager`. |
| **FastMCP server import failure** | Pinned `mcp~=1.28.1` lacked `request_state`. | Upgraded virtual environment to `mcp>=2.2.0`. |
| **Mermaid Syntax Tokenizer Error** | Raw `<ROLE>` tags parsed as unclosed HTML. | Sanitized labels to `ROLE_MAP_role` and quoted node text. |

*(For full troubleshooting logs and details, refer to [`project_technical_guide.md`](project_technical_guide.md#8-troubleshooting--solved-engineering-challenges)).*

---

## 11. Environment Configuration Reference (`.env`)

```env
# ── AI Models ─────────────────────────────────────────────────────────────
OPENAI_API_KEY=sk-proj-...

# ── PostgreSQL + pgvector ────────────────────────────────────────────────
DATABASE_URL=postgresql://rag_user:rag_password@localhost:5432/enterprise_rag

# ── Google Cloud OAuth 2.0 PKCE ───────────────────────────────────────────
GOOGLE_CLIENT_ID=226714713434-67bati2e5sj8kmqg0g8vuhu0jd82eek8.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-...
GOOGLE_REDIRECT_URI=http://localhost:8501/
REQUIRE_GOOGLE_AUTH=true

# ── Firebase Admin SDK (Custom Claims) ───────────────────────────────────
FIREBASE_SERVICE_ACCOUNT_PATH=service_account.json
FIREBASE_PROJECT_ID=226714713434

# ── Role Mapping (Fallback for Standard Google ID tokens) ─────────────────
ROLE_MAP_engineer=kenono2000@gmail.com
ROLE_MAP_finance_executive=kenono2000@gmail.com
ROLE_MAP_hr_manager=kenono2000@gmail.com

# ── GitHub & Autonomous SDLC Agent ───────────────────────────────────────
GITHUB_TOKEN=github_pat_...
SDLC_SANDBOX_ROOT=.
SDLC_TEST_COMMAND=python -m pytest -q
SDLC_PUSH=false
```

---

## 12. Application Execution & Verification Guide

### 1. Setup Virtual Environment
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### 2. Start PostgreSQL with pgvector
```powershell
docker compose up -d postgres
```

### 3. Run Automated Tests (37/37 Passing)
```powershell
python -m pytest -v
```

### 4. Start the FastAPI Microservice
```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
- Interactive Swagger UI: **`http://localhost:8000/docs`**
- Health Probe: **`http://localhost:8000/health`**

### 5. Launch the Streamlit Interactive UI
```powershell
python -m streamlit run streamlit_app.py --server.port 8501
```
- Access in Browser: **`http://localhost:8501`**

### 6. Run the FastMCP Gateway
```powershell
python -m app.mcp
```

---

## 13. Key Engineering Takeaways

| Architecture Pattern | Implementation in Project | Enterprise Value |
| :--- | :--- | :--- |
| **In-Database RBAC** | `allowed_roles ?| $2::text[]` | Eliminates recall starvation and prevents sensitive data leaks into app memory. |
| **Vector Indexing** | `pgvector` HNSW (`m=16, ef=64`) | Sub-millisecond similarity queries over 1536-dimensional embeddings. |
| **Stateless OAuth State** | HMAC-SHA256 signed `state` | Eliminates server-side session stores; immune to browser redirects & restarts. |
| **Clock Skew Leeway** | PyJWT `leeway=60` | Absorbs minor NTP drift between local systems and Google Cloud auth servers. |
| **Loop-Aware asyncpg** | Auto pool recycle on loop close | Solves event loop destruction errors across Streamlit reruns. |
| **AST Code Guardrails** | Python `ast.walk` visitor | Blocks dynamic execution sinks (`eval`, `exec`) before code execution. |
| **Self-Correction Loops** | LangGraph conditional edges | Enables autonomous agents to heal broken code using pytest failure traces. |

---

> 📖 **For exhaustive technical blueprints, mathematical formulas, and step-by-step setup guides, consult [`project_technical_guide.md`](project_technical_guide.md).**