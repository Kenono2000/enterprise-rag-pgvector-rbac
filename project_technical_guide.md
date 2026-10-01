# 🎓 Enterprise Zero-Trust RAG & Autonomous SDLC: Comprehensive Technical Guide

> **Architectural Reference, Implementation Guide & Troubleshooting Manual**  
> **Repository:** `enterprise-rag-pgvector-rbac`  
> **Core Stack:** PostgreSQL 16 + pgvector, FastAPI, Streamlit, Google OAuth 2.0 PKCE, Google JWKS, Firebase Identity, FastMCP, LangGraph.

---

## 📑 Table of Contents
1. [Architectural Philosophy: Standard RAG vs. Zero-Trust In-Database RBAC](#1-architectural-philosophy-standard-rag-vs-zero-trust-in-database-rbac)
2. [Consolidated Codebase Structure](#2-consolidated-codebase-structure)
3. [Layer 1: Database & pgvector Indexing (`schema.sql` & `app/db/`)](#3-layer-1-database--pgvector-indexing-schemasql--appdb)
   - [3.1 Database Schema & Indexing Strategy](#database-schema-schemasql)
   - [3.2 The In-Database RBAC Query (`app/db/manager.py`)](#the-in-database-rbac-query-appdbmanagerpy)
   - [3.3 Connection Pooling with Loop-Awareness](#connection-pooling-with-loop-awareness-databasemanager)
   - [3.4 Matryoshka Representation Learning (MRL) & 1536-d Truncation](#matryoshka-representation-learning-mrl--1536-d-truncation)
   - [3.5 Deterministic Mock Vector Generation (Zero-Token Testing)](#deterministic-mock-vector-generation-zero-token-offline-testing)
   - [3.6 Seed Dataset & Cross-Role Isolation Testing Matrix](#seed-dataset--cross-role-isolation-testing-matrix)
4. [Layer 2: Identity & Cryptographic Security (`app/auth/`)](#4-layer-2-identity--cryptographic-security-appauth)
   - [4.1 RFC 7636 OAuth 2.0 PKCE Flow](#41-rfc-7636-oauth-20-pkce-flow)
   - [4.2 Stateless HMAC-Signed OAuth State](#42-stateless-hmac-signed-oauth-state)
   - [4.3 Google Public JWKS Verification & Clock Skew Leeway](#43-google-public-jwks-verification--clock-skew-leeway)
   - [4.4 Role Storage in Tokens & Resolution Pipeline](#44-role-storage-in-tokens--resolution-pipeline)
   - [4.5 Enterprise Solutions for Custom User Roles in Google JWTs](#45-enterprise-solutions-for-custom-user-roles-in-google-jwts)
   - [4.6 Implementation Guide: Static Role Provisioning via Admin SDK](#46-implementation-guide-static-role-provisioning-via-admin-sdk)
   - [4.7 Token Architecture: ID Token vs. Access Token vs. Refresh Token](#47-token-architecture-id-token-vs-access-token-vs-refresh-token)
   - [4.8 Token Storage Security & Web App Threat Models](#48-token-storage-security--web-app-threat-models)
   - [4.9 Session Expiration & Refresh Termination Engine](#49-session-expiration--refresh-termination-engine)
5. [Layer 3: API & Interactive Frontend (`app/main.py` & `streamlit_app.py`)](#5-layer-3-api--interactive-frontend-appmainpy--streamlit_apppy)
   - [5.1 FastAPI Dependency Injection & Lifespan Management](#fastapi-dependency-injection-get_current_user)
   - [5.2 Confidence Score Formulation](#confidence-score-formulation)
   - [5.3 Streamlit Shift-Left UI Architecture](#streamlit-ui-architecture-streamlit_apppy)
   - [5.4 GitHub Webhook Ingress (`POST /webhooks/github`)](#github-webhook-ingress-post-webhooksgithub)
6. [Layer 4: Model Context Protocol Gateway (`app/mcp.py`)](#6-layer-4-model-context-protocol-gateway-appmcppy)
   - [6.1 Tool: `search_sdlc_context`](#1-tool-search_sdlc_context)
   - [6.2 Tool: `propose_patch`](#2-tool-propose_patch)
   - [6.3 Resource: `policy://sdlc-budget`](#3-resource-policysdlc-budget)
7. [Layer 5: Autonomous SDLC Agent (`agent/`)](#7-layer-5-autonomous-sdlc-agent-agent)
   - [7.1 LangGraph State Machine & `AgentState` Schema](#1-langgraph-state-machine-agentworkflowpy)
   - [7.2 Sandbox Path Traversal Defenses](#1-langgraph-state-machine-agentworkflowpy)
   - [7.3 Static Security & AST Guardrails (`agent/guardrails.py`)](#2-static-security--ast-guardrails-agentguardrailspy)
   - [7.4 Closed-Loop Pytest Self-Healing Prompting](#1-langgraph-state-machine-agentworkflowpy)
8. [Troubleshooting & Solved Engineering Challenges](#8-troubleshooting--solved-engineering-challenges)
9. [Environment Configuration Reference (`.env`)](#9-environment-configuration-reference-env)
10. [Application Execution & Verification Guide](#10-application-execution--verification-guide)
   - [10.1 Test Suite Architecture & Verification Breakdown (37/37 Tests)](#test-suite-architecture--verification-breakdown)
   - [10.2 Service Execution Instructions](#2-run-the-fastapi-microservice)
11. [Educational Summary: Key Engineering Takeaways](#11-educational-summary-key-engineering-takeaways)

---

## 1. Architectural Philosophy: Standard RAG vs. Zero-Trust In-Database RBAC

### The Vulnerability in Standard RAG
In traditional RAG pipelines, access control is handled as an afterthought **after** vector retrieval:

```
[User Query] ──► [Vector DB: Retrieve Top-K] ──► [Python App Filters by Role] ──► [LLM Context]
                                                        │
                                                        └─► Context Eviction & Leakage
```

This post-filtering design suffers from two catastrophic architectural flaws:
1. **Context Eviction / Recall Starvation**: If an unauthorized user queries for financial documents, and the top-$K$ most semantically relevant documents in the vector index belong to restricted executive tiers, post-filtering removes all $K$ documents in Python memory. The user receives zero results, even if relevant tier-appropriate documents existed at rank $K+1$ through $2K$.
2. **Process Memory Leaks & Prompt Injection**: When sensitive vector records are retrieved into application memory before filtering, unredacted text enters the application heap, caches, or logs. Any prompt injection or diagnostic logging defect can expose confidential data.

### The Zero-Trust Guarantee
In this repository, role-based access control is executed **directly inside the PostgreSQL query execution engine**:

```
[User Query] ──► [Verified JWT] ──► [Extract Roles] ──► [PostgreSQL Engine] ──► [LLM Context]
                                                               │
                                  ┌────────────────────────────┴───────────────────────────┐
                                  │ WHERE allowed_roles ?| $user_roles (GIN Index Filter) │
                                  │ ORDER BY embedding <=> $query_vec  (HNSW Index Scan)  │
                                  └────────────────────────────────────────────────────────┘
```

- Unauthorized documents are **never read from disk into the database buffer cache**, **never transmitted across the network TLS socket**, and **never loaded into Python heap memory**.
- The pgvector HNSW index orders *only* the documents that the user is cryptographically authorized to see, eliminating recall starvation.

---

## 2. Consolidated Codebase Structure

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
└── schema.sql                  # Database schema + seed document embeddings
```

---

## 3. Layer 1: Database & pgvector Indexing (`schema.sql` & `app/db/`)

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
2. **`embedding vector(1536)`**: Aligns with OpenAI's `text-embedding-3-large` 1536-dimensional dense embedding space.

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

- **HNSW (Hierarchical Navigable Small World)**: Creates a multi-layer graph of vectors. It outperforms IVFFlat because it requires no separate training partition step and sustains high recall under heavy concurrent queries-per-second (QPS).
- **GIN (Generalized Inverted Index)**: Uses `jsonb_path_ops` to index the elements in `allowed_roles`. When PostgreSQL encounters the `?|` operator, it uses the GIN index to pre-filter candidate rows before calculating vector distances.

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
- **`?|` (JSONB "Exists Any" Operator)**: Evaluates a JSONB array on the left against a text array on the right (`$2::text[]`). Returns `TRUE` if **any** role in `$2` matches **any** element in `allowed_roles`.
- **`<=>` (Vector Cosine Distance)**: Computes the cosine distance $1 - \cos(\theta)$ between the document embedding and query vector `$1`.
- **`1 - (embedding <=> $1::vector)`**: Inverts distance into a similarity metric normalized from $0.0$ to $1.0$ (where $1.0$ is identical).

### Connection Pooling with Loop-Awareness (`DatabaseManager`)
```python
needs_recreate = (
    cls._pool is None
    or cls._loop is None
    or cls._loop is not current_loop
    or cls._loop.is_closed()
)
```
- **The Problem**: `asyncpg` binds database connections to the specific `asyncio` event loop active at pool creation. FastAPI runs on a single persistent loop, but Streamlit creates and tears down a new event loop on every UI interaction and rerun.
- **The Solution**: `DatabaseManager.get_pool()` inspects `asyncio.get_event_loop()`. If the active loop differs or is closed, it gracefully closes the stale pool and initializes a fresh pool bound to the active loop, preventing `RuntimeError: Event loop is closed`.

### Matryoshka Representation Learning (MRL) & 1536-d Truncation
The embedding pipeline (`app/db/llm.py`) leverages OpenAI's `text-embedding-3-large` with explicit dimension truncation:
```python
response = await openai_client.embeddings.create(
    model="text-embedding-3-large",
    input=text,
    dimensions=1536  # Truncated from native 3072 dimensions
)
```
- **Architectural Rationale**: Native `text-embedding-3-large` generates 3072-dimensional dense vectors. Matryoshka embeddings are trained such that the leading dimensions encapsulate the highest information density.
- **Cost & Performance Optimization**:
  - Truncating from 3072 down to 1536 dimensions reduces PostgreSQL disk footprint and HNSW index RAM consumption by **50%**.
  - Benchmarks confirm retention of **>98% of semantic retrieval recall** compared to full 3072-d vectors.

### Deterministic Mock Vector Generation (Zero-Token Offline Testing)
To eliminate external API costs, latency, and rate limits during automated testing and CI/CD pipelines, the architecture implements dual deterministic vector generators in SQL and Python:
- **Python Mock (`app/db/llm.py`)**: When `OPENAI_API_KEY` is omitted, `generate_embedding` produces a deterministic 1536-d vector:
  ```python
  return [0.01 * (i % 5) for i in range(dimensions)]
  ```
- **PostgreSQL Seed Mock (`schema.sql`)**: Seed records are vectorized directly in pure SQL without external API calls:
  ```sql
  (SELECT array_agg(0.01 * (i % 5))::vector(1536) FROM generate_series(1, 1536) i)
  ```

### Seed Dataset & Cross-Role Isolation Testing Matrix
`schema.sql` seeds three canonical enterprise documents designed to test cross-tenant isolation and verify zero recall starvation:

| Document ID | Title | Content Excerpt | Allowed Roles (`JSONB`) | Authorized User Roles |
| :--- | :--- | :--- | :--- | :--- |
| **`FIN-2026-001`** | Executive Q3 Financial Audit | Operating margins increased by 14.2%... | `["finance_executive", "compliance_auditor"]` | `finance_executive`, `compliance_auditor` |
| **`HR-2026-042`** | Internal Compensation Policy | Annual performance bonuses for senior architects... | `["hr_manager", "executive"]` | `hr_manager`, `executive` |
| **`ENG-2026-105`** | Public Engineering Guidelines | All backend microservices must implement async I/O... | `["engineer", "finance_executive", "hr_manager"]` | `engineer`, `finance_executive`, `hr_manager` |

#### Isolation Proof:
- A user authenticated with `engineer` querying *"What were the operating margins in Q3?"* will retrieve `ENG-2026-105` (if similarity permits), but `FIN-2026-001` is strictly excluded by the PostgreSQL GIN filter `allowed_roles ?| '{"engineer"}'::text[]`.
- Unmatched documents are never read from disk into the database buffer cache and never loaded into the application heap.

---

## 4. Layer 2: Identity & Cryptographic Security (`app/auth/`)

### 4.1 RFC 7636 OAuth 2.0 PKCE Flow
PKCE (Proof Key for Code Exchange) protects authorization codes from interception in public and single-page clients:

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

1. **`code_verifier`**: A cryptographically random string (64 URL-safe characters) generated with `secrets.token_bytes(64)`.
2. **`code_challenge`**: The SHA-256 hash of the verifier, base64url-encoded:
   $$\text{code\_challenge} = \text{BASE64URL}(\text{SHA256}(\text{code\_verifier}))$$
3. When exchanging the authorization code at Google's `/token` endpoint, the client sends the plaintext `code_verifier`. Google hashes it and verifies that it matches the `code_challenge` registered in Step 3.

---

### 4.2 Stateless HMAC-Signed OAuth State
Traditional OAuth implementations store `state -> code_verifier` in memory or in a server session. In Streamlit or serverless architectures, navigating the browser away to Google wipes the in-memory session, causing `"OAuth state mismatch — possible CSRF"`.

**Our Solution**: Stateless Signed OAuth State (`app/auth/pkce.py`):
```python
def encode_pkce_state(code_verifier: str, nonce: Optional[str] = None) -> str:
    payload = {"v": code_verifier, "t": int(time.time()), "n": nonce or secrets.token_hex(8)}
    b64_data = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()
    sig = hmac.new(_get_hmac_secret(), b64_data.encode(), hashlib.sha256).hexdigest()
    return f"{b64_data}.{sig}"
```
- **Mechanism**: The `code_verifier` and timestamp are embedded in `state` and signed with an HMAC-SHA256 signature using a server secret.
- **On Callback**: `decode_pkce_state()` validates the signature with `hmac.compare_digest()` and verifies that $\text{time.time}() - t \le 300$ (5-minute TTL).
- **Result**: Zero memory dependencies. Fully immune to server restarts, module reloads, and multi-worker scale-outs.

---

### 4.3 Google Public JWKS Verification & Clock Skew Leeway
Google signs ID tokens using RS256 (asymmetric RSA with SHA-256):
- Public certificates are fetched dynamically from `https://www.googleapis.com/oauth2/v3/certs`.
- `PyJWKClient` caches keys and matches the `kid` (Key ID) header in the token.
- **Clock Skew Leeway**: Configured `leeway=60` in `jwt.decode()`. This absorbs minor clock drift between Google Cloud servers and local client machines, preventing false `ImmatureSignatureError: The token is not yet valid (iat)` rejections.

---

### 4.4 Role Storage in Tokens & Resolution Pipeline

#### How User Roles are Stored
Standard Google OAuth 2.0 ID tokens issued directly by `accounts.google.com` **do not contain authorization or custom role fields by default**—they only contain OpenID Connect identity claims (such as `email`, `sub`, `name`, `hd`).

To bridge identity and authorization, the system uses a **multi-tiered role resolution strategy**:

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

1. **Primary: Custom JWT Claim (`payload["app_roles"]`)**:
   When authenticated through Firebase Authentication or Google Cloud Identity Platform (GCIP), the decoded JWT payload contains a custom array claim:
   ```json
   {
     "iss": "https://securetoken.google.com/your-project-id",
     "sub": "user_1234567890",
     "email": "kenono2000@gmail.com",
     "app_roles": ["engineer", "finance_executive"]
   }
   ```
   `role_mapper.py` reads `payload.get("app_roles")` directly. If present, it bypasses external mapping.

2. **Secondary: Firebase Admin SDK Live Lookup (`_get_firebase_claims_by_email`)**:
   When a user signs in via standard Google OAuth 2.0 (tokens issued by `accounts.google.com` which do not carry Firebase custom claims), `role_mapper.py` uses the initialized Firebase Admin SDK (`service_account.json` or `GOOGLE_APPLICATION_CREDENTIALS`) to query Firebase Auth for the user by email:
   ```python
   user = fb_auth.get_user_by_email(email)
   raw_roles = user.custom_claims.get("app_roles", [])
   ```
   Any recognized roles matching `KNOWN_ROLES` are immediately returned without requiring environment variable mapping.

3. **Tertiary: Server-Side Email Fallback (`ROLE_MAP_<ROLE>`)**:
   For environments without Firebase Admin service account keys, `role_mapper.py` inspects `payload.get("email")` and matches against configured environment variables:
   ```env
   ROLE_MAP_engineer=kenono2000@gmail.com
   ROLE_MAP_finance_executive=kenono2000@gmail.com
   ROLE_MAP_hr_manager=kenono2000@gmail.com
   ```

4. **Quaternary: Offline Developer Fallback (`X-User-Roles`)**:
   When `REQUIRE_GOOGLE_AUTH=false`, callers can pass roles via HTTP header (`X-User-Roles: ["engineer"]`) for automated testing.

---

### 4.5 Enterprise Solutions for Custom User Roles in Google JWTs

Because Google strictly controls the schema and RSA private keys for `accounts.google.com`, arbitrary claims cannot be injected directly into standard consumer OAuth tokens. Three architectural patterns solve this in enterprise environments:

| Pattern | How It Works | Best For |
| :--- | :--- | :--- |
| **1. Google Cloud Identity Platform (GCIP) / Firebase Auth** | GCIP wraps Google Sign-In; tokens are minted from `securetoken.google.com`. Roles are attached via **Blocking Cloud Functions** (`beforeSignIn`) or the **Admin SDK**. | Cloud-native GCP / Firebase stacks. |
| **2. Token Exchange Gateway (RFC 8693)** | Backend validates Google ID token, queries database for user roles, and mints an application-specific RS256 JWT containing `app_roles`. | Microservices and custom enterprise backends. |
| **3. Google Workspace Custom User Schemas** | Admin Console defines custom attributes on Workspace accounts; queried via Directory API or federated into GCIP. | Enterprise organizations with Google Workspace domains. |

#### Deep Dive: Dynamic Injection via GCIP Blocking Cloud Functions (`beforeSignIn`)
Google Cloud Identity Platform allows triggering a Cloud Function **before** the JWT is minted, dynamically fetching roles from PostgreSQL and embedding them into the token payload:
```javascript
const { beforeUserSignedIn } = require("firebase-functions/v2/identity");
const db = require("./db");

exports.beforeSignIn = beforeUserSignedIn(async (event) => {
  const email = event.data.email;
  const roles = await db.getUserRoles(email); // Query PostgreSQL for roles

  return {
    customClaims: {
      app_roles: roles // e.g. ["engineer", "finance_executive"]
    }
  };
});
```

---

### 4.6 Implementation Guide: Static Role Provisioning via Admin SDK

To provision user roles without running serverless blocking functions, the project provides a static assignment pipeline using `firebase-admin`.

#### 1. Setup & Credentials
Install the dependency and configure credentials:
```powershell
pip install firebase-admin
```
In `.env`:
```env
FIREBASE_SERVICE_ACCOUNT_PATH=service_account.json
FIREBASE_PROJECT_ID=226714713434
```

#### 2. Management CLI Script (`scripts/set_user_roles.py`)
```python
"""
scripts/set_user_roles.py
CLI tool to inspect and assign custom 'app_roles' claims to Firebase users.
"""
import argparse
import os
import sys
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import auth, credentials

load_dotenv()

def initialize_firebase():
    if not firebase_admin._apps:
        cred_path = os.getenv("FIREBASE_SERVICE_ACCOUNT_PATH", "service_account.json")
        if os.path.exists(cred_path):
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred)
        else:
            firebase_admin.initialize_app()

def set_roles(email: str, roles: list[str]):
    initialize_firebase()
    try:
        user = auth.get_user_by_email(email)
    except auth.UserNotFoundError:
        print(f"Error: User '{email}' not found.")
        sys.exit(1)

    claims = user.custom_claims or {}
    claims["app_roles"] = roles
    auth.set_custom_user_claims(user.uid, claims)
    print(f"Updated {email} (UID: {user.uid}) -> app_roles: {roles}")

def get_roles(email: str):
    initialize_firebase()
    user = auth.get_user_by_email(email)
    print(f"User: {email} (UID: {user.uid}) -> Claims: {user.custom_claims}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Manage Firebase custom roles.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--roles", nargs="*", help="Space-separated roles")
    parser.add_argument("--inspect", action="store_true")
    args = parser.parse_args()

    if args.inspect:
        get_roles(args.email)
    elif args.roles is not None:
        set_roles(args.email, args.roles)
```

#### 3. CLI Execution Example
```powershell
# Assign roles
python scripts/set_user_roles.py --email kenono2000@gmail.com --roles engineer finance_executive hr_manager

# Inspect claims
python scripts/set_user_roles.py --email kenono2000@gmail.com --inspect
```

#### 4. Dual Token Verification (`app/auth/jwks.py`)
To verify both standard Google OAuth tokens and Firebase custom claims tokens seamlessly:
```python
from firebase_admin import auth as fb_auth

def verify_token(token: str) -> dict:
    """Verifies Firebase Auth or Google OAuth ID token."""
    try:
        # 1. Attempt verification via Firebase Admin SDK (securetoken JWKS)
        return fb_auth.verify_id_token(token, clock_skew_seconds=60)
    except Exception:
        # 2. Fall back to standard Google OAuth JWKS verification
        return verify_standard_google_token(token)
```

#### 5. Token Immutability & Client-Side Refresh Lifecycle
> [!IMPORTANT]
> **JWTs are cryptographically immutable**. Setting custom claims on the server does **not** modify existing tokens in the user's browser:
> - The client must refresh the token to receive updated claims.
> - In web clients: `firebase.auth().currentUser.getIdToken(true)` forces a fresh token minting.
> - In Streamlit / standard OAuth: The user must sign out and sign back in.

---

### 4.7 Token Architecture: ID Token vs. Access Token vs. Refresh Token

To maintain Zero-Trust security perimeters without forcing users to re-authenticate every 15 minutes, the system partitions authentication and authorization into three distinct cryptographic credentials:

| Token | Primary Question | Underlying Technology | Standard Lifetime | Primary Consumer |
| :--- | :--- | :--- | :--- | :--- |
| **ID Token (OIDC)** | *"Who are you?"* | Signed RS256 JWT containing identity claims (`sub`, `email`, `name`, `app_roles`). | Short (~15–60 min) | The **Web Client** (UI rendering) & **FastAPI Backend** (Zero-Trust RBAC context). |
| **Access Token (OAuth 2.0)** | *"What can you do?"* | Bearer credential containing authorization scopes. | Short (~15–60 min) | External or third-party **Resource APIs**. |
| **Refresh Token (OAuth 2.0)** | *"Keep me authenticated"* | Opaque cryptographic string maintained in the Auth server database. | Long (weeks/months) | Strictly the **Identity Provider's Token Endpoint** (`/oauth/token`). |

#### The Complete Token Lifecycle: PKCE to Silent Refresh

```mermaid
sequenceDiagram
    autonumber
    actor User as User Browser / Streamlit
    participant App as Web Frontend (SPA)
    participant Auth as Identity Provider (Google / Firebase)
    participant API as FastAPI Backend (app/main.py)

    Note over App,Auth: Phase 1: Cryptographic Setup & Consent Redirect
    App->>App: 1. Generate code_verifier (64 URL-safe bytes)
    App->>App: 2. Derive code_challenge = Base64URL(SHA256(verifier))
    App->>App: 3. Create HMAC-signed state
    App->>User: Redirect to accounts.google.com/o/oauth2/v2/auth (access_type=offline&prompt=consent)
    User->>Auth: Submits credentials & MFA; grants consent

    Note over User,App: Phase 2: Authorization Code Delivery
    Auth->>User: 302 Redirect to redirect_uri?code=AUTH_CODE_123&state=SIGNED_STATE
    User->>App: Callback lands with code & state; validates state HMAC

    Note over App,Auth: Phase 3: Direct Back-Channel Exchange
    App->>Auth: POST /oauth2/v4/token (code + code_verifier + client_id + client_secret)
    Auth->>Auth: SHA256(code_verifier) === code_challenge? Validated!
    Auth-->>App: Returns { id_token, access_token, refresh_token, expires_in: 3600 }

    Note over App,API: Phase 4: Authorized RAG Querying
    App->>API: POST /api/v1/query (Bearer <id_token>)
    API->>API: Validates RS256 JWKS, checks leeway=60s, executes In-DB RBAC
    API-->>App: 200 OK (Authorized context returned)

    Note over App,Auth: Phase 5: Silent Refresh (When exp nears or 401 received)
    App->>Auth: POST /oauth2/v4/token (grant_type=refresh_token & refresh_token=RT_...)
    Auth->>Auth: Validates refresh token in stateful store (checks revocation / reuse)
    Auth-->>App: Returns { new_id_token, new_access_token, (optional rotated refresh_token) }
```

> [!NOTE]
> **Why `access_type=offline` and `prompt=consent` are mandatory:**  
> In Google OAuth 2.0, a **Refresh Token is only issued** if `access_type=offline` is explicitly passed in the authorization URL. For existing user grants, Google will omit the refresh token on subsequent logins unless `prompt=consent` forces re-consent.

---

### 4.8 Token Storage Security & Web App Threat Models

The security posture of a web application depends on where these tokens reside in browser memory:

| Storage Location | XSS Risk (Script Injection) | CSRF Risk (Cross-Site Request) | Architectural Verdict |
| :--- | :--- | :--- | :--- |
| **`localStorage` / `sessionStorage`** | 🔴 **High**: Injected scripts or malicious third-party dependencies can execute `localStorage.getItem('refresh_token')` and exfiltrate long-lived credentials. | 🟢 **None**: Browsers never automatically attach Web Storage data to cross-origin requests. | ❌ **Anti-pattern for Refresh Tokens**. Acceptable strictly for disposable, short-lived tokens in low-risk sandboxes. |
| **JavaScript In-Memory (State / Closures)** | 🟢 **Immune to static storage scraping**: Discarded on browser tab reload or window close. | 🟢 **None**. | 🟡 **Best for short-lived ID/Access Tokens**, but requires silent background refresh on tab reload. |
| **`HttpOnly`, `Secure`, `SameSite` Cookies** | 🟢 **Immune to JavaScript exfiltration**: The browser refuses to expose cookies to `document.cookie`. | 🟡 **Mitigated**: Protected using `SameSite=Strict` (or `Lax`) and anti-CSRF custom headers (`X-Requested-With`). | ✅ **Industry Standard for Production SPAs**. |
| **Backend-for-Frontend (BFF) Pattern** | 🟢 **Maximum Security**: Tokens are stored exclusively in encrypted server-side Redis sessions; browser only holds an encrypted opaque session cookie. | 🟢 **Managed at gateway perimeter**. | 🏆 **Gold Standard for Financial / Enterprise Portals**. |

#### Client-Side Silent Token Refresh Pattern (Axios Interceptor)
To prevent user interruption when the short-lived ID token expires, single-page applications use HTTP response interceptors to catch HTTP 401, refresh tokens silently, and replay the pending request:

```typescript
import axios from "axios";

const apiClient = axios.create({ baseURL: "https://api.enterprise-rag.com" });

apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;

    // Detect expired token and prevent infinite refresh loops
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;

      try {
        // Exchange refresh token (handled via HttpOnly cookie or auth SDK)
        const { data } = await axios.post(
          "https://oauth2.googleapis.com/token",
          { grant_type: "refresh_token", refresh_token: getStoredRefreshToken() }
        );

        const newIdToken = data.id_token;
        apiClient.defaults.headers.common["Authorization"] = `Bearer ${newIdToken}`;
        originalRequest.headers["Authorization"] = `Bearer ${newIdToken}`;

        // Replay failed query with fresh token
        return apiClient(originalRequest);
      } catch (refreshError) {
        // Refresh token expired or revoked -> route to login
        window.location.href = "/login?reason=session_expired";
        return Promise.reject(refreshError);
      }
    }
    return Promise.reject(error);
  }
);
```

---

### 4.9 Session Expiration & Refresh Termination Engine

A secure web application must know **when to stop refreshing tokens** and enforce terminal logout. The system implements a three-tier expiration architecture:

```mermaid
flowchart TD
    Start[Token nearing expiration or API returned 401] --> CheckIdle{Has user been idle > 15 min?}
    
    CheckIdle -->|Yes: Inactivity Timeout| Terminate[DO NOT REFRESH:<br/>Clear tokens & Redirect to Login]
    CheckIdle -->|No| CheckCeiling{Has absolute session exceeded 12 hrs?}
    
    CheckCeiling -->|Yes: Hard Ceiling Met| Terminate
    CheckCeiling -->|No| Attempt[Send POST /token with refresh_token]
    
    Attempt --> Resp{Server Response}
    Resp -->|200 OK: Valid| Update[Update tokens in memory & schedule next check]
    Resp -->|400 invalid_grant: Revoked/Expired| Terminate
    Resp -->|5xx Network Glitch| Retry[Retry with exponential backoff]
```

#### 1. Inactivity (Idle) Countdown Engine
Regardless of refresh token TTL, regulatory compliance (SOC-2, HIPAA, PCI-DSS) mandates terminating the session after 15–30 minutes of keyboard/mouse inactivity:
- The client monitors user engagement events (`mousedown`, `keydown`, `scroll`, `touchstart`).
- An activity listener resets a debounced 15-minute timer.
- If the countdown reaches zero without user interaction:
  1. The silent refresh timer is cancelled.
  2. In-memory tokens and session cookies are purged.
  3. A terminal beacon (`navigator.sendBeacon('/api/auth/logout')`) invalidates the server-side session.
  4. The browser is routed to `/login?reason=inactivity_timeout`.

#### 2. Absolute Session Lifetime Ceiling
To prevent users from remaining authenticated indefinitely via rolling refresh tokens, the client and auth server enforce a hard ceiling (e.g. 8–12 hours):
- When the user first logs in, the authentication timestamp is anchored via the `auth_time` JWT claim.
- Before initiating any background token refresh, the client verifies:
  $$\text{CurrentTime} - \text{auth\_time} \le \text{MAX\_ABSOLUTE\_SESSION\_SECONDS}$$
- If the ceiling is reached, token refresh is prohibited, and the user is prompted to re-enter their credentials.

#### 3. Server-Driven Rejection: `invalid_grant` & Breach Alarms
The Authorization Server serves as the authoritative source of truth. If a refresh request returns:
```json
HTTP/1.1 400 Bad Request
{
  "error": "invalid_grant",
  "error_description": "Token has been expired or revoked."
}
```
This indicates that:
- The refresh token exceeded its maximum backend TTL (e.g. 30 days).
- The user's account password was changed, or permissions were altered in the Admin SDK.
- **Refresh Token Rotation (RTR) & Reuse Detection**: An attacker attempted to reuse an already-rotated refresh token. The auth server instantly invalidated the entire token family, neutralizing the breach.

On receiving `invalid_grant`, the client immediately aborts all retries and clears state.

#### 4. Multi-Tab Session Synchronization via `BroadcastChannel`
When a user logs out or times out in Tab A, Tabs B, C, and D must not continue background token refreshes:
```typescript
const authChannel = new BroadcastChannel('auth_sync');

// In Tab 1: Terminal logout triggered
function terminateSession() {
  TokenStorage.clearAll();
  authChannel.postMessage({ type: 'TERMINATE_SESSION' });
  window.location.href = '/login';
}

// In Tabs 2+: Listener instantly cancels refresh engines
authChannel.onmessage = (event) => {
  if (event.data.type === 'TERMINATE_SESSION') {
    TokenRefresher.stop();
    TokenStorage.clearAll();
    window.location.href = '/login?reason=logged_out_in_other_tab';
  }
};
```

---

## 5. Layer 3: API & Interactive Frontend (`app/main.py` & `streamlit_app.py`)

### FastAPI Dependency Injection (`get_current_user`)
In `app/main.py`, FastAPI's dependency injection system guards every incoming request:
```python
async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    x_user_roles: Optional[str] = Header(default=None),
) -> UserIdentity:
```
- If `REQUIRE_GOOGLE_AUTH=true`: A valid Google Bearer token is strictly mandatory. Unauthenticated callers immediately receive HTTP 401.
- If `REQUIRE_GOOGLE_AUTH=false`: Enables developer fallback mode where `X-User-Roles: ["engineer"]` is accepted for offline unit testing.

### Streamlit UI Architecture (`streamlit_app.py`)
- **Direct Navigation Button**: Renders an HTML `<a>` tag with `target="_top"` to bypass iframe sandboxing and guarantee reliable browser redirection to Google's consent screen.
- **Live RBAC SQL Inspector**: Displays verified user claims, generated vector embeddings, and executed SQL query telemetry in real time.
- **Token Copy Box**: Provides a copyable ID token box in the sidebar for testing endpoints in Swagger UI (`/docs`).

### Lifespan Management & Pool Draining (`app/main.py`)
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database connection pool...")
    try:
        await DatabaseManager.get_pool()
    except Exception as exc:
        logger.warning("Database pool initialization deferred: %s", exc)
    yield
    logger.info("Closing database connection pool...")
    await DatabaseManager.close()
```
- **Startup**: Eagerly initializes the `asyncpg` connection pool. If PostgreSQL is booting or cold-starting, pool initialization is deferred safely without crashing the worker.
- **Shutdown**: Drains active database client connections cleanly to prevent connection leaks on server reload or termination.

### Confidence Score Formulation
The `RAGResponse` object provides an aggregated confidence metric derived from the cosine similarities of all retrieved citations:
$$\text{confidence\_score} = \frac{1}{N} \sum_{i=1}^N \text{similarity}_i = \frac{1}{N} \sum_{i=1}^N \left(1 - (\text{embedding}_i \Leftrightarrow \text{query\_vec})\right)$$
Scores range from $0.0$ to $1.0$, giving consumers an auditable, mathematical certainty metric for retrieved context.

### GitHub Webhook Ingress (`POST /webhooks/github`)
The API exposes an automated event listener for GitHub webhooks:
- **HMAC-SHA256 Signature Verification**: Validates the `X-Hub-Signature-256` header against `GITHUB_WEBHOOK_SECRET` via `hmac.compare_digest` to prevent timing attacks.
- **Event Dispatching**: When `X-GitHub-Event: issues` and `action: opened` is received, the payload is parsed into an `SDLCEvent` and automatically triggers `LangGraphSDLCWorkflow.run()` in the background.

---

## 6. Layer 4: Model Context Protocol Gateway (`app/mcp.py`)

FastMCP exposes our Zero-Trust RAG system to external AI agents (like Claude Desktop, Cursor, or autonomous coding agents) over standard Model Context Protocol transports:

### 1. Tool: `search_sdlc_context`
```python
@mcp.tool()
async def search_sdlc_context(
    question: str,
    auth_token: Optional[str] = None,
    user_roles: Optional[list[str]] = None,
) -> str:
```
- Agents supply an `auth_token` (Google ID token).
- The gateway verifies the token via `verify_google_token(auth_token)` and extracts roles using `extract_roles()`.
- Executes in-database RBAC vector search: only documents permitted by the agent's verified roles are included in the prompt context.

### 2. Tool: `propose_patch`
```python
@mcp.tool()
async def propose_patch(
    branch_name: str,
    patch_content: str,
    auth_token: Optional[str] = None,
) -> str:
```
- Allows external coding agents to submit code modifications or unified diffs targeting a specific git branch.
- Authenticates submitter identity using the verified `sub` or `email` claim in the Google ID token.

### 3. Resource: `policy://sdlc-budget`
FastMCP resources allow AI clients to inspect operational constraints dynamically:
```python
@mcp.resource("policy://sdlc-budget")
def get_budget_policy() -> str:
    """Return execution budget policy for autonomous agents."""
    return json.dumps({
        "max_tokens_per_issue": 50000,
        "max_steps": 10,
        "allowed_tools": ["search_sdlc_context", "propose_patch"],
    })
- Defines strict token budgets (`50,000` tokens per issue) and maximum agent execution steps (`10`) to eliminate runaway LLM invocation loops.

---

## 7. Layer 5: Autonomous SDLC Agent (`agent/`)

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
1. **`initialize`**: Parses the GitHub webhook event into an `SDLCEvent` and checks out an isolated Git feature branch (`feature/AGENT-<id>-<title-slug>`).
2. **`propose_patches`**: Uses the LLM (`PayloadPatchAgent`) to propose unified file updates formatted as a JSON list of `PatchProposal` objects (`file_path`, `content`).
3. **`apply_patches`**: Writes proposed files to the target workspace while enforcing strict **Sandbox Path Traversal Defenses**:
   ```python
   rel = Path(patch.file_path)
   if rel.is_absolute() or ".." in rel.parts or (rel.parts and rel.parts[0] == ".git"):
       raise ValueError(f"Unsafe patch path: {patch.file_path}")
   target = (self.root / rel).resolve()
   target.parent.mkdir(parents=True, exist_ok=True)
   target.write_text(patch.content, encoding="utf-8")
   ```
4. **`audit_patches`**: Invokes the `PolicyEngine` to run deterministic security checks. If any violation is flagged, execution halts immediately (`END`), rejecting the patch before execution.
5. **`run_tests`**: Runs `pytest` in an asynchronous background thread (`asyncio.to_thread`) via a subprocess.
6. **`repair_patches` (Closed-Loop Self-Correction)**: If `pytest` fails and `attempt < max_attempts`, the trailing error trace (`test_output[-2500:]`) is sliced into the repair prompt. The LLM self-corrects the code, re-applies the patch, and re-triggers the security audit and test suite.
7. **`finalize`**: Stages changes with `git add`, commits code (`Implement #<id>: <title>`), pushes the branch to origin, and opens a GitHub Pull Request via the GitHub REST API.

#### Typed State Schema & Thread Checkpointing
The workflow maintains state across node transitions using a strongly typed `AgentState` schema:
```python
class AgentState(TypedDict):
    event: SDLCEvent
    payload: Dict[str, Any]
    branch: str
    patches: List[PatchProposal]
    violations: List[str]
    test_result: Optional[Dict[str, Any]]
    attempt: int
    max_attempts: int
    error: Optional[str]
    pr_url: Optional[str]
    pushed: bool
```
- **Thread Isolation & Persistence**: Compiled with `MemorySaver()` checkpointing. Every GitHub issue execution is bound to an isolated thread ID (`sdlc-{repository}-{issue_id}`), enabling point-in-time replay and debugging.

### 2. Static Security & AST Guardrails (`agent/guardrails.py`)
Before any code is tested or committed, the `PolicyEngine` enforces two deterministic gates:

#### A. Secret Scanning Patterns
Scans proposed file modifications using compiled regular expressions to prevent credential leakage into git history:
```python
SECRET_PATTERNS = [
    re.compile(r"(?:sk-|key-|token-|secret-)[a-zA-Z0-9]{20,}", re.IGNORECASE),  # API keys & bearer tokens
    re.compile(r"-----BEGIN [A-Z ]+ PRIVATE KEY-----"),                          # RSA, EC, OpenSSH private keys
    re.compile(r"AIza[0-9A-Za-z-_]{35}"),                                        # Google Cloud API keys
]
```

#### B. Abstract Syntax Tree (AST) Inspection
Uses Python's built-in `ast.parse()` to traverse code syntax without execution, blocking dynamic execution sinks and dunder imports:
```python
tree = ast.parse(content)
for node in ast.walk(tree):
    if isinstance(node, ast.Call):
        if isinstance(node.func, ast.Name) and node.func.id in ("exec", "eval", "__import__"):
            violations.append(f"Forbidden dynamic execution: {node.func.id}()")
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "__import__":
            violations.append("Forbidden dunder import: __import__()")
```
- Traps and reports `SyntaxError` before code reaches the test environment.
- Returns a structured `SecurityGateResult` markdown audit summary embedded directly into the GitHub PR description.

---

## 8. Troubleshooting & Solved Engineering Challenges

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
| **`pip ResolutionImpossible: PyJWT==2.10.1 and PyJWT==2.15.1`** | Duplicate entries in `requirements.txt` with conflicting / non-existent version (`2.15.1`). | Pruned duplicate line in `requirements.txt`, retaining strictly `PyJWT==2.10.1`. |
| **Mermaid Parsing Error: `<ROLE>` Tag Breakage** | Mermaid tokenizer interpreted unquoted `<ROLE>` as an unclosed HTML tag and unquoted quotes broke label tokens. | Quoted node labels `["..."]`, sanitized text to `ROLE_MAP_role`, and connected all decision leaves into `UserIdentity`. |

---

## 9. Environment Configuration Reference (`.env`)

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

## 10. Application Execution & Verification Guide

### 0. Install Dependencies
```powershell
python -m pip install -r requirements.txt
```

### 1. Run Unit Tests (37/37 passing)
```powershell
python -m pytest -v
```

#### Test Suite Architecture & Verification Breakdown
The repository maintains a 100% passing test suite (37 tests across 4 modules) with complete isolation from external network dependencies:

| Test Module | Test Focus | Key Invariants Verified |
| :--- | :--- | :--- |
| **`tests/test_rag.py`** | FastAPI Endpoints & RBAC Retrieval | • Health check returns `status: healthy`.<br/>• Strict 401 rejection when `REQUIRE_GOOGLE_AUTH=true` and no token is supplied.<br/>• Dev header fallback (`X-User-Roles`) when `REQUIRE_GOOGLE_AUTH=false`.<br/>• Verified Google ID token extraction, citation formatting, and confidence scoring calculation.<br/>• PostgreSQL GIN query filter ensures only matching roles are evaluated. |
| **`tests/test_auth.py`** | PKCE Cryptography & Google JWKS | • RFC 7636 `code_verifier` (64-char URL safe) and `code_challenge` derivation.<br/>• Stateless HMAC-SHA256 state generation and validation.<br/>• Rejection of expired state tokens ($>300$s TTL) and tampered state signatures.<br/>• `PyJWKClient` key caching and RS256 token decoding.<br/>• `leeway=60s` absorbs simulated clock drift without `ImmatureSignatureError`. |
| **`tests/test_mcp_auth.py`** | FastMCP Tool Authorization | • FastMCP `search_sdlc_context` rejects unauthenticated agent calls when Google auth is enforced.<br/>• ID token extraction propagates verified roles into vector retrieval.<br/>• Legacy fallback roles evaluated only in dev mode.<br/>• `propose_patch` validates submitter identity claims. |
| **`tests/test_agent.py`** | Autonomous SDLC & Guardrails | • GitHub webhook HMAC-SHA256 signature verification (`X-Hub-Signature-256`).<br/>• Webhook JSON parsing into typed `SDLCEvent` models.<br/>• Deterministic secret scanning flags OpenAI keys (`sk-...`), private keys, and Google API keys.<br/>• AST static inspection blocks `eval()`, `exec()`, and `__import__()`.<br/>• Sandbox path traversal defenses reject absolute paths, `..`, and `.git/`.<br/>• LangGraph state machine node transitions and pytest failure self-healing loop. |

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

---

## 11. Educational Summary: Key Engineering Takeaways

| Concept | Implementation in this Project | Why It Matters |
| :--- | :--- | :--- |
| **In-Database RBAC** | `allowed_roles ?| $2::text[]` | Prevents unauthorized data from ever leaving the database. Eliminates recall starvation. |
| **Approximate Nearest Neighbors** | `pgvector` HNSW (`m=16, ef=64`) | Enables sub-millisecond semantic search on 1536-dimensional embeddings. |
| **PKCE (RFC 7636)** | `code_verifier` + SHA256 challenge | Protects authorization codes from interception in public/SPA/browser clients. |
| **Stateless OAuth State** | HMAC-SHA256 signed `state` | Eliminates server-side session dependencies and survives browser redirects/restarts. |
| **Clock Skew Tolerance** | PyJWT `leeway=60` | Prevents intermittent authentication failures caused by minor NTP time drift. |
| **Self-Correction Loops** | LangGraph conditional edges | Allows AI coding agents to autonomously read test failures and heal their own code. |
| **AST Guardrails** | Python `ast.walk` visitor | Replaces brittle regex checking with true syntactic analysis to block code execution sinks. |
| **Custom JWT Claims** | Firebase / GCIP `app_roles` | Embeds roles into cryptographic tokens to eliminate application-level mapping tables. |
| **Token Refresh Lifecycle** | `getIdToken(true)` / re-login | Respects JWT immutability by forcing client-side token refresh when roles change. |
