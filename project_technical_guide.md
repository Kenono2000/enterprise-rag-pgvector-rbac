# 🎓 Enterprise Zero-Trust RAG & Autonomous SDLC: Comprehensive Technical Guide

This document provides a complete technical walkthrough of the **`enterprise-rag-pgvector-rbac`** project. It is written to serve as both an architectural reference and an educational guide on building production-grade, zero-trust AI systems.

---

## 1. Architectural Philosophy: Standard RAG vs. Zero-Trust In-Database RBAC

### The Vulnerability in Standard RAG
In traditional RAG pipelines, access control is handled **after** vector retrieval:
```
User Query -> Vector DB (Retrieves top-k) -> Python App filters by user role -> LLM Context
```
This post-filtering design suffers from two catastrophic flaws:
1. **Context Eviction / Recall Starvation**: If a user queries for financial documents, and the top-5 most similar documents in the database are restricted executive documents, post-filtering removes all 5 documents. The user receives zero results, even if authorized documents existed at rank 6 through 10.
2. **Memory Leaks & Prompt Injection**: If sensitive chunks enter application memory or an intermediary cache, any prompt injection or logging bug can leak confidential data.

### The Zero-Trust Guarantee
In this repository, role-based access control is executed **directly inside the PostgreSQL query execution engine**:
```
User Query -> Verified JWT -> Extract Roles -> SQL Query [WHERE allowed_roles ?| $user_roles] -> Vector Order -> LLM Context
```
- Unauthorized documents are **never read from disk into the database buffer**, **never transmitted over the network**, and **never loaded into Python memory**.
- The pgvector HNSW index orders *only* the documents that the user is cryptographically authorized to see.

---

## 2. Layer 1: Database & pgvector Indexing (`schema.sql` & `app/db/`)

### Database Schema (`schema.sql`)
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
```

#### Key Technical Decisions:
1. **`allowed_roles JSONB NOT NULL`**: Roles are stored as a JSON array of strings (e.g. `["finance_executive", "compliance_auditor"]`).
2. **`embedding vector(1536)`**: Matches OpenAI's `text-embedding-3-large` 1536-dimensional vector space.

### Indexing Strategy
```sql
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
- **HNSW (Hierarchical Navigable Small World)**: Creates a multi-layer graph of vectors. It outperforms IVFFlat because it requires no separate training step and provides higher recall at high queries-per-second (QPS).
- **GIN (Generalized Inverted Index)**: Uses `jsonb_path_ops` to index the values in `allowed_roles`. When PostgreSQL encounters the `?|` operator, it uses the GIN index to pre-filter rows before calculating vector distances.

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
#### Deep Dive into the SQL Operators:
- **`?|` (JSONB "Exists Any" Operator)**: Takes a JSONB array on the left and a string array on the right (`$2::text[]`). Returns `TRUE` if **any** string in `$2` matches **any** element in `allowed_roles`.
- **`<=>` (Vector Cosine Distance)**: Calculates the cosine distance `1 - cos(theta)` between document embedding and query vector `$1`.
- **`1 - (embedding <=> $1::vector)`**: Inverts distance into a similarity score from 0.0 to 1.0 (where 1.0 is identical).

### Connection Pooling with Loop-Awareness (`DatabaseManager`)
```python
needs_recreate = (
    cls._pool is None
    or cls._loop is None
    or cls._loop is not current_loop
    or cls._loop.is_closed()
)
```
- **The Problem**: `asyncpg` binds database connections to the specific `asyncio` event loop on which they were created. FastAPI runs on a persistent loop, but Streamlit creates and tears down a new event loop on every script rerun.
- **The Solution**: `DatabaseManager.get_pool()` inspects `asyncio.get_event_loop()`. If the loop changes or closes, it gracefully closes the stale pool and creates a new one bound to the active loop, preventing `RuntimeError: Event loop is closed`.

---

## 3. Layer 2: Identity & Cryptographic Security (`app/auth/`)

```mermaid
sequenceDiagram
    autonumber
    actor User as User Browser
    participant App as Streamlit / Client
    participant Google as accounts.google.com
    participant API as FastAPI / Gateway
    participant JWKS as Google Public JWKS

    User->>App: Clicks "Sign in with Google"
    App->>App: generate_code_verifier() & derive_code_challenge()
    App->>App: encode_pkce_state(verifier) [HMAC-SHA256 Signed]
    App->>Google: Redirect with code_challenge & signed state
    Google->>User: Renders Consent Screen
    User->>Google: Approves Login
    Google->>App: Redirects to localhost:8501/?code=XXX&state=YYY
    App->>App: decode_pkce_state(state) -> verifies HMAC & extracts verifier
    App->>Google: POST /token (code, verifier, client_id, client_secret)
    Google->>App: Returns {id_token, access_token}
    App->>API: Calls /api/v1/query with Bearer <id_token>
    API->>JWKS: Fetches Google Public Certs (RS256)
    API->>API: Validates signature, audience, exp, leeway=60s
    API->>API: extract_roles(payload) -> ['finance_executive', ...]
```

### 1. RFC 7636 OAuth 2.0 PKCE (`app/auth/pkce.py`)
PKCE (Proof Key for Code Exchange) protects authorization codes from interception:
1. **`code_verifier`**: A cryptographically random string (64 URL-safe characters) generated with `secrets.token_bytes(64)`.
2. **`code_challenge`**: The SHA-256 hash of the verifier, base64url-encoded:
   $$\text{code\_challenge} = \text{BASE64URL}(\text{SHA256}(\text{code\_verifier}))$$
3. When exchanging the authorization code at Google's `/token` endpoint, the client sends the plain `code_verifier`. Google hashes it and verifies it matches the `code_challenge` sent in step 1.

### 2. Stateless HMAC-Signed OAuth State
Traditional OAuth apps store `state -> code_verifier` in memory or in a server session. In Streamlit or serverless environments, navigating the browser away to Google resets the session, causing `"OAuth state mismatch — possible CSRF"`.

**Our Solution**: Stateless Signed OAuth State:
```python
def encode_pkce_state(code_verifier: str, nonce: Optional[str] = None) -> str:
    payload = {"v": code_verifier, "t": int(time.time()), "n": nonce or secrets.token_hex(8)}
    b64_data = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    sig = hmac.new(_get_hmac_secret(), b64_data.encode(), hashlib.sha256).hexdigest()
    return f"{b64_data}.{sig}"
```
- **How it works**: The `code_verifier` and timestamp are embedded in `state` and signed with an HMAC-SHA256 signature using a server secret.
- **On Callback**: `decode_pkce_state()` validates the signature with `hmac.compare_digest()` and checks that `time.time() - t <= 300` (5-minute expiration).
- **Result**: Zero memory dependencies. Immune to server reboots, module reloads, and multi-worker setups.

### 3. Google Public JWKS Verification (`app/auth/jwks.py`)
Google signs ID tokens using RS256 (asymmetric RSA with SHA-256).
- Public certificates are published at `https://www.googleapis.com/oauth2/v3/certs`.
- PyJWKClient caches the keys and matches the `kid` (Key ID) header in the token.
- **Clock Skew Leeway**: We configured `leeway=60` in `jwt.decode()`. This grants a 60-second buffer to absorb minor clock drift between Google Cloud servers and local machines, preventing `ImmatureSignatureError: The token is not yet valid (iat)`.

### 4. Role Mapping (`app/auth/role_mapper.py`)
1. **Firebase / Google Identity Platform**: Checks for the custom claim `payload["app_roles"]`.
2. **Environment Variable Fallback**: If `app_roles` is absent, evaluates `ROLE_MAP_<ROLE>` (e.g. `ROLE_MAP_engineer=kenono2000@gmail.com`).

---

## 4. Layer 3: API & Interactive Frontend (`app/main.py` & `streamlit_app.py`)

### FastAPI Dependency Injection (`get_current_user`)
In `app/main.py`, FastAPI's dependency injection system guards every request:
```python
async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    x_user_roles: Optional[str] = Header(default=None),
) -> UserIdentity:
```
- If `REQUIRE_GOOGLE_AUTH=true`: A valid Google Bearer token is strictly mandatory. Unauthenticated callers immediately receive HTTP 401.
- If `REQUIRE_GOOGLE_AUTH=false`: Enables developer fallback mode where `X-User-Roles: ["engineer"]` is accepted for offline unit testing.

### Streamlit UI Architecture (`streamlit_app.py`)
- **Direct Navigation Button**: Renders an HTML `<a>` tag with `target="_top"` to bypass iframe sandboxing and ensure clean browser redirection to Google's consent screen.
- **Live RBAC SQL Inspector**: Displays the verified user claims, generated vector embeddings, and executed SQL query in real-time.
- **Token Copy Box**: Provides a copyable ID token box in the sidebar for testing endpoints in Swagger UI (`/docs`).

---

## 5. Layer 4: Model Context Protocol Gateway (`app/mcp.py`)

FastMCP exposes our Zero-Trust RAG system to external AI agents (like Claude Desktop, Cursor, or autonomous coding agents):

```python
@mcp.tool()
async def search_sdlc_context(
    question: str,
    auth_token: Optional[str] = None,
    user_roles: Optional[list[str]] = None,
) -> str:
```
- Agents can supply an `auth_token` (Google ID token).
- The gateway verifies the token via `verify_google_token(auth_token)` and extracts roles using `extract_roles()`.
- If unauthenticated and `REQUIRE_GOOGLE_AUTH=true`, the tool rejects the agent's request.

---

## 6. Layer 5: Autonomous SDLC Agent (`agent/`)

The `agent/` package houses an autonomous software development agent that processes GitHub issues, writes code patches, audits them, and runs automated verification.

```mermaid
stateDiagram-v2
    [*] --> initialize
    initialize --> propose_patches
    propose_patches --> apply_patches
    apply_patches --> audit_patches
    
    audit_patches --> run_tests : Security Gate PASSED
    audit_patches --> [*] : Security Gate FAILED (Violations)
    
    run_tests --> finalize : Tests PASSED
    run_tests --> repair_patches : Tests FAILED (Attempts < Max)
    run_tests --> [*] : Max Attempts Reached
    
    repair_patches --> apply_patches
    finalize --> [*]
```

### 1. LangGraph State Machine (`agent/workflow.py`)
Built using LangGraph's `StateGraph`:
1. **`initialize`**: Parses the GitHub webhook event and creates an isolated Git branch (`feature/AGENT-<id>-<title>`).
2. **`propose_patches`**: Uses LLM (`PayloadPatchAgent`) to propose unified file updates.
3. **`apply_patches`**: Safely writes files to the target workspace while enforcing path traversal defenses (rejecting `..`, absolute paths, or modifications to `.git/`).
4. **`audit_patches`**: Invokes the `PolicyEngine` to run deterministic security checks.
5. **`run_tests`**: Runs `pytest` in a background subprocess.
6. **`repair_patches` (Self-Correction Loop)**: If `pytest` fails, the error trace (`stderr`) is captured and sent back to the LLM to self-heal the patch.
7. **`finalize`**: Stages changes with `git add`, creates a commit, pushes the branch, and opens a GitHub Pull Request via the GitHub REST API.

### 2. Static Security & AST Guardrails (`agent/guardrails.py`)
Before any code is tested or committed, the `PolicyEngine` enforces two deterministic gates:
1. **Secret Scanning**: Scans code diffs using compiled regular expressions for API keys, private keys (`-----BEGIN PRIVATE KEY-----`), and cloud credentials.
2. **Abstract Syntax Tree (AST) Inspection**: Uses Python's built-in `ast.parse()` to traverse the code structure:
   - Detects and blocks dynamic execution functions: `eval()`, `exec()`.
   - Blocks dunder imports: `__import__()`.
   - Rejects syntax errors before runtime.

---

## 7. Educational Summary: Key Engineering Takeaways

| Concept | Implementation in this Project | Why It Matters |
| :--- | :--- | :--- |
| **In-Database RBAC** | `allowed_roles ?| $2::text[]` | Prevents unauthorized data from ever leaving the database. Eliminates recall starvation. |
| **Approximate Nearest Neighbors** | `pgvector` HNSW (`m=16, ef=64`) | Enables sub-millisecond semantic search on 1536-dimensional embeddings. |
| **PKCE (RFC 7636)** | `code_verifier` + SHA256 challenge | Protects authorization codes from interception in public/SPA/browser clients. |
| **Stateless OAuth State** | HMAC-SHA256 signed `state` | Eliminates server-side session dependencies and survives browser redirects/restarts. |
| **Clock Skew Tolerance** | PyJWT `leeway=60` | Prevents intermittent authentication failures caused by minor NTP time drift. |
| **Self-Correction Loops** | LangGraph conditional edges | Allows AI coding agents to autonomously read test failures and heal their own code. |
| **AST Guardrails** | Python `ast.walk` visitor | Replaces brittle regex checking with true syntactic analysis to block code execution sinks. |
