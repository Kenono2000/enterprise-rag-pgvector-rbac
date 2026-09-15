# 🛡️ Enterprise Zero-Trust RAG Microservice

<div align="center">

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-4169E1?logo=postgresql&logoColor=white)](https://www.postgresql.org/)
[![pgvector](https://img.shields.io/badge/pgvector-enabled-00B8D9?logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![Auth0](https://img.shields.io/badge/Auth0-SSO-EB5424?logo=auth0&logoColor=white)](https://auth0.com/)

**High-throughput retrieval-augmented generation with in-database RBAC and `pgvector`.**

</div>

---

### 👤 Architect
**[Ken Wong](https://www.linkedin.com/in/kenwong-architect/)**  
*Target stack: Python, FastAPI, PostgreSQL, pgvector, FastMCP, Auth0*

---

## 🚀 Live Architecture Artifacts

| Component | Description | Link |
| :--- | :--- | :--- |
| **Visual UI** | Shift-left RBAC Demo | [enterprise-rag-pgvector-rbac.streamlit.app](https://enterprise-rag-pgvector-rbac.streamlit.app) |
| **API Docs** | Live OpenAPI / Swagger | [enterprise-rag-api-ksez.onrender.com/docs](https://enterprise-rag-api-ksez.onrender.com/docs) |
| **Repository** | Auditable Source | [github.com/Kenono2000/enterprise-rag-pgvector-rbac](https://github.com/Kenono2000/enterprise-rag-pgvector-rbac) |

---

## 🏛️ System Architecture

```mermaid
flowchart TB
    subgraph Client ["Client Layer"]
        user[User / Service]
    end

    subgraph Auth ["Security Layer"]
        auth0[Auth0\nIdentity & Role Claims]
    end

    subgraph App ["FastAPI RAG Application"]
        direction TB
        api[API Endpoint\nPOST /api/v1/query]
        embed[Embedding Engine\nText-to-Vector]
        orchestrator[Search Orchestrator]
        llm[LLM Generation\nCitations & Confidence]
    end

    subgraph Data ["Data Layer"]
        db[(PostgreSQL + pgvector\nRow-Level Security)]
    end

    subgraph Tools ["MCP Ecosystem"]
        mcp[FastMCP Gateway\nIdentity-Aware Tools]
    end

    user -->|1. Request Token| auth0
    auth0 -->|2. JWT Claims| user
    user -->|3. Authenticated Query| api
    api -->|4. Vectorize| embed
    embed -->|5. Embedding| orchestrator
    orchestrator -->|6. SQL + Vector + RBAC| db
    db -->|7. Filtered Context| orchestrator
    orchestrator -->|8. Contextual Prompt| llm
    llm -->|9. Result| api
    api -->|10. Answer + Citations| user

    mcp -.->|Governed Access| orchestrator

    style db fill:#f9f,stroke:#333,stroke-width:2px
    style auth0 fill:#dfd,stroke:#333,stroke-width:2px
    style App fill:#f0f8ff,stroke:#007acc,stroke-dasharray: 5 5
```

**Core flow:** Auth0 issues identity and role claims → FastAPI generates a query embedding → `pgvector` performs a similarity search filtered by row-level role metadata → the LLM receives only authorized context → a typed response returns with citations and a confidence score.

---

## ✨ Key Features

### Governed Tool-Calling & CI/CD Evaluation Harness

An exploratory testbed evaluating the operational boundaries and failure modes of agentic tool-calling within software delivery pipelines.

#### Key Focus Areas
* **Bounded FastMCP Tool Contracts:** Exposing strictly typed schemas to LLM clients, preventing arbitrary shell command execution.
* **Context Hydration via pgvector:** Retrieving architecture decision records (ADRs) and interface specs deterministically via in-database RBAC rather than saturating context windows.
* **Automated Failure Triage:** Testing closed-loop failure triage by piping failing `pytest` logs and AST checks into the model to evaluate real-world code repair versus hallucinated fixes.
* **Token Budgeting & Auditability:** Tracking request IDs, token usage, and latency across all tool-calling invocations.

---

## 🏗️ Technical Deep Dive

### 1. In-Database Zero-Trust RBAC
Retrieval is not just about similarity; it is about **authority**.

- **Level:** Row-level security (RLS) simulation via metadata filtering.
- **Mechanism:** PostgreSQL `JSONB` indexing and the `?|` operator match JWT role claims against document `allowed_roles` **inside the vector search query itself**.
- **Benefit:** Prevents unauthorized data leakage by ensuring the LLM never sees context outside the caller's access domain.

### 2. Autonomous SDLC with LangGraph
The project implements a self-healing development loop.

- **State Machine:** Uses **LangGraph** to manage the cycle of `propose → apply → audit → test → repair`.
- **Security Gate:** An automated **Policy Engine** audits every proposed patch for secret leakage or unsafe imports before execution.
- **Resilience:** If tests fail, the agent receives the traceback and attempts to repair the code automatically (configurable retry limit).

### 3. High-Performance Vector Search
- **Engine:** `pgvector` with **HNSW** (Hierarchical Navigable Small World) indexing.
- **Optimized I/O:** Uses `asyncpg` for non-blocking database calls, critical for high-throughput microservices.
- **Validation:** Pydantic DTOs enforce strict schema validation for all RAG inputs and outputs.

### 4. Enterprise-Ready Architecture
- **Identity-Aware MCP:** FastMCP integration lets external tools/agents interact with the RAG system while respecting RBAC rules.
- **Modular Design:** Clear separation between the RAG microservice (`app/`) and the SDLC orchestration layer (`sdlc_harness/`).

---

## 🔁 Autonomous SDLC Lifecycle

This project demonstrates a full lifecycle autonomous development workflow, from issue ingestion to production deployment with security gates.

```mermaid
flowchart TD
    subgraph Trigger ["1. Trigger"]
        issue[Developer Opens Issue] --> webhook[GitHub Webhook]
    end

    subgraph Agent ["2. Autonomous Agent (LangGraph)"]
        direction TB
        harness[SDLC Harness]
        
        subgraph Loop ["Inner Loop: Self-Healing Development"]
            direction LR
            propose[Propose] --> apply[Apply]
            apply --> audit[Security Audit]
            audit --> test[Run Tests]
            test -- "Fail (Retry)" --> propose
        end
        
        harness --> Loop
    end

    subgraph Git ["3. Version Control"]
        Loop -- "Pass" --> branch[Create Branch]
        branch --> commit[Commit Code]
        commit --> push[Push & Open PR]
    end

    subgraph Pipeline ["4. Enterprise CI/CD Pipeline"]
        direction TB
        push --> ci[GitHub Actions]
        
        subgraph Checks ["Security & Build Gates"]
            direction LR
            sast[CodeQL SAST]
            sca[Snyk SCA]
            dast[ZAP DAST]
        end
        
        ci --> Checks
        Checks --> reviewer{Human Review}
    end

    subgraph Prod ["5. Production"]
        reviewer -- "Approve" --> deploy[Deploy to Cloud]
    end

    webhook --> harness
    
    style Loop fill:#fff9c4,stroke:#fbc02d,stroke-width:2px,stroke-dasharray: 5 5
    style Checks fill:#e1f5fe,stroke:#01579b,stroke-width:2px
    style Agent fill:#f5f5f5,stroke:#333
    style Pipeline fill:#f0f8ff,stroke:#333
```

---

## 🧪 Local Development

### 1. Setup Environment
```powershell
# Create and activate virtual environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### 2. Run Tests
```powershell
python -m pytest -q
```

### 3. Start Infrastructure & API
```powershell
# Start PostgreSQL with pgvector
docker compose up -d postgres

# Start the API with hot-reload
python -m uvicorn sdlc_harness_main:app --reload --port 8000
```

> 💡 **Note:** The API is available at `http://localhost:8000`, and interactive documentation is at `/docs`.

---

## 🧩 SDLC Harness Internals

The custom harness handles the fine-grained orchestration of patch application, security validation, and automated repair.

```mermaid
flowchart TD
    subgraph Input ["Ingestion"]
        webhook[GitHub Event] --> verify[Verify Signature]
        verify --> parse[Parse SDLC Event]
    end

    subgraph Workspace ["Environment Setup"]
        parse --> branch[Create Feature Branch]
    end

    subgraph Logic ["Orchestration Engine (State Machine)"]
        direction TB
        branch --> state_init[Initialize State]
        state_init --> propose[Agent: Propose Patches]
        propose --> apply[Apply in Sandbox]
        
        subgraph Gate ["Security Gate"]
            apply --> audit{Policy Audit}
            audit -- "Secrets/Unsafe" --> reject[Reject & Exit]
        end

        subgraph Test ["Validation"]
            audit -- "Clean" --> run_tests[Run Test Command]
            run_tests --> test_res{Tests Pass?}
        end

        subgraph Repair ["Self-Correction"]
            test_res -- "No" --> limit{Retries Left?}
            limit -- "Yes" --> repair[Agent: Analyze & Fix]
            repair --> apply
            limit -- "No" --> fail[Fail Workflow]
        end
    end

    subgraph Output ["Completion"]
        test_res -- "Yes" --> commit[Git Commit]
        commit --> push_check{SDLC_PUSH?}
        push_check -- "Yes" --> pr[Create Pull Request]
        push_check -- "No" --> local[Finish Locally]
        pr --> complete[Return Success]
    end

    style Gate fill:#fff4dd,stroke:#d4a017
    style Repair fill:#fce4ec,stroke:#c2185b
    style Test fill:#e1f5fe,stroke:#01579b
    style Logic fill:#f5f5f5,stroke:#333
```

> **Note:** GitHub Actions is a better production runner for checkout, secrets, isolation, retries, logs, and PR integration. The custom harness remains useful for the agent, RAG context, and organization-specific governance logic.

### Example Payload
```json
{
  "issue": {
    "number": 125,
    "title": "Fix value",
    "body": "Update the value."
  },
  "repository": {
    "full_name": "Kenono2000/enterprise-rag-pgvector-rbac"
  },
  "patches": [
    {
      "file_path": "src/value.py",
      "content": "VALUE = 2\n"
    }
  ]
}
```

### Example Response
```json
{
    "status": "completed",
    "issue_id": "125",
    "branch": "feature/AGENT-125-fix-value",
    "tests": "python -m pytest -q",
    "pushed": true,
    "pull_request_url": "https://github.com/Kenono2000/enterprise-rag-pgvector-rbac/pull/1",
    "pull_request_created": true
}
```

---