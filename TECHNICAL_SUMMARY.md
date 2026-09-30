# 📘 Enterprise Zero-Trust RAG: Comprehensive Technical Session Summary

**Project:** `enterprise-rag-pgvector-rbac`  
**Architect:** Ken Wong ([LinkedIn](https://linkedin.com/in/kenwong-architect) | [GitHub](https://github.com/Kenono2000/enterprise-rag-pgvector-rbac))  
**Core Technologies:** PostgreSQL, pgvector, FastAPI, Streamlit, Google Cloud OAuth 2.0 PKCE, Google JWKS, Firebase Identity, FastMCP, LangGraph.

---

## 1. System Architecture Overview

The system implements a production-grade **Zero-Trust Retrieval-Augmented Generation (RAG)** microservice coupled with an isolated **Autonomous SDLC Agent**.

```
[ User Browser / Streamlit ]
         │ (1) OAuth PKCE Sign-In
         ▼
[ Google Identity Provider ]
         │ (2) Returns RS256 ID Token
         ▼
[ Streamlit / API Client ]
         │ (3) Authorization: Bearer <id_token>
         ▼
[ FastAPI Gatekeeper (app/main.py) ]
         │ (4) Google JWKS Verification (RS256, leeway=60s)
         │ (5) Role Extraction (Firebase claims / ROLE_MAP_ fallback)
         ▼
[ PostgreSQL + pgvector (schema.sql) ]
         │ (6) WHERE allowed_roles ?| $user_roles::text[]
         │ (7) ORDER BY embedding <=> $query_vector
         ▼
[ Grounded LLM Completion (OpenAI gpt-4o) ]
```

---

## 2. Solved Engineering Challenges & Troubleshooting History

| Error Encountered | Root Cause | Engineering Solution |
| :--- | :--- | :--- |
| **`403 Identity Toolkit API disabled`** | Identity Toolkit API was disabled in GCP project `226714713434`. | Enabled via: `gcloud services enable identitytoolkit.googleapis.com`. |
| **`INSUFFICIENT_PERMISSION`** | GCP default credentials lacked Firebase IAM permissions. | Downloaded Firebase Admin SDK service account key (`service_account.json`). |
| **`CONFIGURATION_NOT_FOUND`** | Firebase Auth not initialized in Firebase Console. | Initialized Firebase Auth provider in the Firebase console. |
| **`OAuth state mismatch — possible CSRF`** | Streamlit wipes `st.session_state` when the browser navigates away to Google and returns. | Implemented **Stateless HMAC-SHA256 Signed State** (`encode_pkce_state` / `decode_pkce_state`). Zero memory dependency; immune to reloads. |
| **Browser stuck on Google login / `play.google.com/log`** | `<meta http-equiv="refresh">` is ignored in DOM `<div>` elements; `play.google.com/log` is just background telemetry. | Implemented a direct HTML `<a>` button with `target="_top"` that breaks out of iframes and immediately redirects the top window. |
| **`400 Bad Request: client_secret is missing`** | Google OAuth client registered as "Web application" strictly requires `client_secret` at `/token`. | Added `GOOGLE_CLIENT_SECRET=GOCSPX-...` to `.env` and enhanced `pkce.py` to extract exact JSON errors from Google. |
| **`The token is not yet valid (iat)`** | Clock skew between local Windows system clock and Google cloud NTP servers. | Configured `leeway=60` in `jwt.decode()` per OAuth2/JWT RFC 7519 specifications. |
| **`Active JWT Role Claims: []`** | Role mappings in `.env` were commented out; claims absent in default token. | Configured `ROLE_MAP_engineer`, `ROLE_MAP_finance_executive`, `ROLE_MAP_hr_manager` for `kenono2000@gmail.com`. |
| **`POST /api/v1/query 401 Unauthorized`** | Zero-trust enforcement rejected unauthenticated request in Swagger UI (`/docs`). | Added copyable ID token expander to Streamlit sidebar to paste into Swagger **Authorize 🔓** button. |
| **FastMCP `ImportError: server support not installed`** | `crewai` pinned `mcp~=1.28.1` which lacked `mcp.server.request_state` needed by `fastmcp 4.0.3`. | Upgraded `mcp>=2.2.0` in virtual environment. |

---

## 3. Core Architectural Implementations

### A. In-Database Zero-Trust RBAC (`schema.sql` & `app/db/manager.py`)
- **Vulnerability Solved**: Post-retrieval filtering in standard RAG causes context starvation and memory leakage.
- **Implementation**:
  ```sql
  SELECT document_id, title, content, allowed_roles, 
         1 - (embedding <=> $1::vector) AS similarity
  FROM enterprise_documents
  WHERE allowed_roles ?| $2::text[]
    AND (embedding_model = 'text-embedding-3-large' OR embedding_model IS NULL)
  ORDER BY embedding <=> $1::vector
  LIMIT $3;
  ```
- **`?|` Operator**: PostgreSQL JSONB "exists any" operator checks document permissions against user roles before computing vector distances.
- **Indexing**: Multi-layer **HNSW index** (`vector_cosine_ops`) for sub-millisecond approximate nearest neighbors + **GIN index** (`jsonb_path_ops`) on `allowed_roles`.

### B. Stateless HMAC-SHA256 OAuth State (`app/auth/pkce.py`)
- Embeds the PKCE `code_verifier` and timestamp into an opaque string signed with HMAC-SHA256.
- When Google redirects back to `http://localhost:8501/?code=...&state=...`, `decode_pkce_state()` verifies the signature with constant-time `hmac.compare_digest()` and validates `time.time() - t <= 300` (5-minute TTL).
- Survives process restarts, multi-worker environments, and Streamlit session resets.

### C. FastMCP Gateway with OAuth (`app/mcp.py`)
- Exposes SDLC context and patch submission to external AI agents.
- Functions accept `auth_token: Optional[str] = None`. When passed, roles are verified against Google's public JWKS (`verify_google_token`), preventing role spoofing.

### D. Autonomous SDLC Agent (`agent/workflow.py`)
- 7-node LangGraph state machine: `initialize` -> `propose_patches` -> `apply_patches` -> `audit_patches` -> `run_tests` -> `repair_patches` -> `finalize`.
- **Self-Healing Loop**: Captures `pytest` failure traces (`stderr`) and loops back to LLM for autonomous self-correction up to `max_repairs`.
- **Deterministic Guardrails (`agent/guardrails.py`)**: AST traversal (`ast.parse`) blocks dynamic code sinks (`eval()`, `exec()`, `__import__()`), and regex scans for API keys / private keys.

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
├── tests/                      # 🧪 Consolidated 100% Passing Test Suite (37 tests)
│   ├── test_rag.py             # FastAPI endpoints & Zero-Trust RBAC tests
│   ├── test_auth.py            # PKCE & Google JWKS token tests
│   ├── test_mcp_auth.py        # FastMCP OAuth auth_token verification tests
│   └── test_agent.py           # SDLC LangGraph workflow & guardrails tests
│
├── streamlit_app.py            # 🖥️ Interactive Demo UI (PKCE Sign-In + Live Search)
├── main.py                     # Root entry point -> runs app.main:app
├── docker-compose.yml          # PostgreSQL + pgvector container
└── schema.sql                  # Database schema + seed document embeddings
```

---

## 5. Environment Configuration Template (`.env`)

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

# ── Role Mapping (Fallback for Google ID tokens) ──────────────────────────
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

## 6. How to Run the Applications

### 1. Run Unit Tests (37/37 passing)
```powershell
python -m pytest -v
```

### 2. Run the FastAPI Microservice
```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```
- Swagger Documentation: **`http://localhost:8000/docs`**
- Health Endpoint: **`http://localhost:8000/health`**

### 3. Run the Streamlit Interactive Demo UI
```powershell
python -m streamlit run streamlit_app.py --server.port 8501
```
- Web Application: **`http://localhost:8501`**

### 4. Run the FastMCP Gateway
```powershell
python -m app.mcp
```
