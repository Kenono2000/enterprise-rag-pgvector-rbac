# 🛡️ Enterprise Zero-Trust RAG Microservice

**High-Throughput Retrieval-Augmented Generation with In-Database RBAC & `pgvector`**

**Architect:** [Ken Wong](https://www.linkedin.com/in/kenwong-architect/)  
**Target Stack:** Python, FastAPI, PostgreSQL, `pgvector`, FastMCP, Auth0

---

## 🚀 Live Interactive Demos

- **🎨 Production-Ready Visual UI:** Test the real-world Shift-Left RBAC filtering in a production-grade interface (powered by actual `asyncpg` and `pgvector`):  
  👉 **[https://enterprise-rag-pgvector-rbac.streamlit.app/](https://enterprise-rag-pgvector-rbac.streamlit.app/)**
- **⚡ Modular API & Swagger UI:** Test the raw, production-ready microservice endpoints:  
  👉 **[https://enterprise-rag-api-ksez.onrender.com/docs](https://enterprise-rag-api-ksez.onrender.com/docs)**
- **🤖 Autonomous SDLC Gateway:** Access the FastMCP gateway for agent-governed git operations:  
  👉 **`https://enterprise-rag-mcp.fastmcp.app/mcp`**

---


## 🔑 Core Problem Solved

Standard RAG (Retrieval-Augmented Generation) architectures often retrieve sensitive context chunks into application memory and filter user permissions at the API layer. In multi-tenant enterprise environments, this creates severe data-leakage, indirect prompt-injection, and compliance risks (SOC2/GDPR).

This reference architecture solves this by implementing **Shift-Left Security**:
- 🔐 **Auth0 Identity Integration:** Extracts validated JWT claims (roles, tenant ID) via OAuth 2.0 PKCE.
- 🗄️ **In-Database RBAC Filtering:** Passes JWT roles directly into PostgreSQL using the JSONB existence operator (`?|`). This ensures the database *only* returns authorized chunks during the HNSW vector search—unauthorized data **never** enters application memory or LLM prompts.
- 🗜️ **Matryoshka Truncation (1536d):** Compresses 3072d vectors down to 1536d to respect `pgvector`'s optimal HNSW indexing ceiling, retaining >98% semantic accuracy while optimizing storage and query latency.
- 🤖 **Agent-Ready MCP Server:** Implements the Model Context Protocol (MCP) via `fastmcp`, allowing AI Agents to perform secure, tool-based retrieval with identity-aware filtering baked in.
- 📄 **Deterministic API Contracts:** Synthesizes LLM responses into strongly-typed Pydantic DTOs, featuring grounded citations and cosine confidence scores for strict auditability.

---

## 🗄️ Real Vector Database & Indexed RAG Implementation

While `app.py` provides a frictionless mocked demo, **`main.py` is a genuine, production-ready RAG pipeline**. It implements the following real-world capabilities:

1. **Real `asyncpg` Connection Pooling:** Production-ready asynchronous database connections to PostgreSQL, ensuring high throughput and low latency under concurrent enterprise load.
2. **Real Matryoshka Embedding Generation:** Dynamically generates actual 1536-dimensional embeddings for incoming queries via live embedding APIs (no hardcoded mock vectors).
3. **Real `pgvector` HNSW Index Querying:** Executes genuine vector similarity searches combined with PostgreSQL JSONB role filtering. The database engine leverages real HNSW indexes to efficiently scan and return *only* authorized chunks, preventing costly full-table scans.
4. **Real Ingestion Pipeline:** The `/api/v1/ingest` endpoint demonstrates real document processing, embedding generation, and insertion into the `pgvector`-enabled table with associated RBAC metadata.
5. **Deterministic Pydantic Contracts:** Returns strongly-typed, real-world API responses (`RAGResponse`) featuring grounded citations, actual cosine similarity confidence scores, and evaluated role metadata.

---

## 🤖 Autonomous SDLC Agent Harness (FastMCP + Git Automation)

An event-driven orchestration engine that transforms Jira/GitHub feature specifications into tested pull requests via multi-agent execution loops and deterministic tool governance.

*   **Deterministic Tool Contracts:** Engineered a FastMCP execution runtime enforcing typed Pydantic tool schemas, path-traversal prevention, step budgets, and parameter validation.
*   **Shift-Left Context Injection:** Injected relevant codebase patterns and ADRs via PostgreSQL `pgvector` with in-database role filtering (`?|` operator) to ensure architectural alignment.
*   **Automated Quality Gates:** Integrated automated test-repair loops, AST validation, and secret scanning before opening pull requests for human review.
*   **Cost-Aware Orchestration:** Implemented a state machine with hard step-limits and token budgets to prevent runaway agent execution and ensure predictable operational costs.

### Custom SDLC code vs. GitHub Actions

The custom harness and GitHub Actions solve different parts of the delivery problem:

| Capability | Custom SDLC harness | GitHub Actions |
|---|---|---|
| Agent planning and repair loops | Customizable agent, RAG context, typed patch proposals, token and step budgets | Usually delegated to a service or action step |
| Security and architectural policy | Repository-specific AST, secret, ADR, and RBAC checks | Workflow permissions, environment protection, and required checks |
| Repository execution | Must manage sandboxing, concurrency, cleanup, and retries | Isolated hosted or self-hosted runners with logs and artifacts |
| Git and pull requests | Implemented manually through Git and the GitHub API | Built-in checkout, credentials, branch, status, and PR integrations |
| Triggers and delivery | Requires an API endpoint, webhook authentication, and job persistence | Native issue, push, pull-request, schedule, and manual triggers |
| Operational maturity | Must be built and maintained | Provides timeouts, secrets, permissions, logs, and reruns |

GitHub Actions should generally provide the execution and delivery plumbing, while the custom harness should provide the differentiated agent, RAG, and governance logic. The current harness is useful as a reference implementation and local prototype; a production deployment should move long-running execution into a GitHub Actions workflow or another durable job runner. The two approaches are complementary rather than mutually exclusive.

### Running the SDLC workflow locally

The end-to-end workflow is exposed at `POST /webhooks/github`. It verifies an optional GitHub webhook signature, parses the issue, invokes the typed patch agent, applies patches inside `SDLC_SANDBOX_ROOT`, runs the configured test command, evaluates security guardrails, commits the branch, and optionally pushes it and opens a GitHub pull request.

Create an untracked `.env` file in the project root:

```dotenv
SDLC_SANDBOX_ROOT=.
SDLC_TEST_COMMAND=python -m pytest -q
SDLC_PUSH=true
GITHUB_TOKEN=<token>
```

`SDLC_PUSH` and `GITHUB_TOKEN` are optional. Leave `SDLC_PUSH=false` or omit it to create only a local branch and commit. Set `GITHUB_WEBHOOK_SECRET` as well when validating signed GitHub webhook deliveries.

### Manual end-to-end test

Use two PowerShell terminals. The first terminal runs the API; the second sends a fake GitHub issue event to it.

In terminal 1, from the project directory, make sure `.env` contains these safe local-test values:

```dotenv
SDLC_SANDBOX_ROOT=.
SDLC_TEST_COMMAND=python -m pytest -q
SDLC_PUSH=false
```

Start PostgreSQL because the API initializes its database pool at startup:

```powershell
cd C:\src\enterprise-rag-pgvector-rbac
docker compose up -d postgres
python -m uvicorn sdlc_harness_main:app --reload --port 8000
```

Leave that terminal running. In terminal 2, send a test issue containing one typed patch. This patch adds a harmless Python constant, so the existing test suite should remain green:

```powershell
cd C:\src\enterprise-rag-pgvector-rbac
$payload = @'
{
  "issue": {"number": 987654, "title": "Manual SDLC smoke test", "body": "Verify the local workflow."},
  "repository": {"full_name": "owner/repository"},
  "patches": [{"file_path": "sdlc_smoke_test.py", "content": "VALUE = 2\n"}]
}
'@

try {
  Invoke-RestMethod `
    -Uri http://localhost:8000/webhooks/github `
    -Method Post `
    -ContentType "application/json" `
    -Body $payload
}
catch {
  $_.ErrorDetails.Message
}
```

A successful local response includes `"status": "completed"`, a branch named `feature/AGENT-987654-manual-sdlc-smoke-test`, and `"pushed": false`. For remote delivery, restart Uvicorn after changing `.env`, set `SDLC_PUSH=true`, configure a valid `GITHUB_TOKEN`, and use a real repository name. The response should then include `"pushed": true`, `"pull_request_created": true`, and a `pull_request_url`. Verify the result with:

```powershell
git status
git branch --show-current
git log -1 --oneline
python -m pytest -q
```

The workflow created a local branch, applied the patch, ran tests, and committed the change. It did not push or create a pull request because `SDLC_PUSH=false`. Delete the smoke-test branch and file after inspection if this was only a demonstration:

```powershell
git checkout main
git branch -D feature/AGENT-987654-manual-sdlc-smoke-test
Remove-Item sdlc_smoke_test.py -ErrorAction SilentlyContinue
```

Only after the local flow works should you set `SDLC_PUSH=true` and provide `GITHUB_TOKEN`; restart Uvicorn so the updated `.env` is loaded. The token needs permission to write repository contents and pull requests, and `repository.full_name` must be the real `owner/repository` value.

For GitHub delivery validation, set `GITHUB_WEBHOOK_SECRET`; the endpoint then requires `X-Hub-Signature-256`. A failed test can be repaired when the injected agent returns `repair_patches`. Run `python -m pytest -q` to validate the complete local workflow.

---

## 🎙️ Interview Positioning

**The Narrative:** 
> "Most teams experiment with AI by asking developers to prompt assistants inside an IDE. In this repository, I architected the **governed control plane**: the agent receives a feature ticket, pulls authorized architectural patterns via Shift-Left `pgvector` search, operates inside bounded FastMCP tool schemas with token budgets, and verifies itself against local test gates before a human ever looks at the pull request."

---

## 🏛️ Architecture Blueprint



```mermaid
sequenceDiagram
    participant Agent as AI Agent / Client
    participant API as FastAPI / MCP Server
    participant DB as PostgreSQL + pgvector
    participant LLM as OpenAI (gpt-4o)

    Agent->>API: Query (Question + JWT Role Array)
    API->>API: Generate 1536d Matryoshka Embedding
    API->>DB: Query with `?|` JSONB Role Filter + Vector Search
    DB-->>API: Return ONLY Authorized Chunks (Shift-Left Security)
    API->>LLM: Synthesize Answer with Grounded Context
    LLM-->>API: Deterministic JSON Response
