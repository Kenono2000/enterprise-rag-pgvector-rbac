# Enterprise RAG Observability, Distributed Tracing & Hardening Guide

Comprehensive architectural record and implementation reference for end-to-end OpenTelemetry distributed tracing, persistent Jaeger storage, and runtime execution hardening across Streamlit, FastAPI, and MCP Server in the `enterprise-rag-pgvector-rbac` platform.

| Metadata | Details |
| :--- | :--- |
| **Date** | 2026-10-08 |
| **Topic** | Enterprise RAG Observability, Distributed Tracing & Execution Hardening |
| **Source** | `enterprise-rag-pgvector-rbac` (Git Branch: `feature/issues-15-16-17-hardening`) |
| **Status** | Production Hardened / Verified (95 Passed, 1 Skipped) |

---

## 1. Executive Summary

This release resolves core operational, telemetry, and runtime reliability bottlenecks across the Enterprise RAG stack. Key outcomes include:
* **Full-Stack Observability**: End-to-end tracing across Streamlit UI interactions, FastAPI REST/middleware layers, LLM generation pipelines, and Model Context Protocol (MCP) tool executions.
* **Persistent Jaeger Storage**: Replaced ephemeral in-memory span storage with an embedded Badger LSM-tree database backed by Docker volumes, preventing data loss across container recycles.
* **Concurrency & Event Loop Hardening**: Eliminated cross-thread `RuntimeError: Event loop is closed` failures by binding `AsyncOpenAI` client instances directly to active thread event loops.
* **Grounding Calibration**: Refined system prompts to permit natural synthesized answers while preserving strict anti-hallucination boundaries and citation requirements.

---

## 2. Distributed Tracing Architecture

The platform uses **OpenTelemetry (OTel)** with the **OTLP gRPC Exporter** pushing spans to **Jaeger All-In-One**.

```
[User Browser]
       │
       ▼
[Streamlit UI (8501)] ──── (Span: chat_interaction)
       │                              │
       ├──────────────────────────────┼──────────┐
       ▼                              ▼          ▼
[FastAPI Gateway (8000)]    [FastMCP Gateway]  [LLM Service]
 (Span: http_request)        (Span: mcp_tool)   (Span: rag.generate)
       │                              │          │
       └──────────────────────────────┼──────────┘
                                      ▼
                        [OTLP gRPC Exporter (4317)]
                                      │
                                      ▼
                    [Jaeger All-In-One (Badger Storage)]
                                      │
                                      ▼
                           [Jaeger UI (16686)]
```

### Telemetry Configuration & Ports

| Component | Port | Protocol | Purpose |
| :--- | :--- | :--- | :--- |
| **Jaeger UI** | `16686` | HTTP | Web UI trace search and timeline inspection |
| **OTLP gRPC** | `4317` | gRPC | Standard telemetry span ingestion endpoint |
| **OTLP HTTP** | `4318` | HTTP | Alternative OTLP ingestion endpoint |
| **FastAPI** | `8000` | HTTP | REST API & Documentation (`/docs`) |
| **Streamlit** | `8501` | HTTP | Enterprise UI frontend |
| **PostgreSQL / pgvector** | `5432` | TCP | RBAC metadata and vector embeddings |

### Standardized Span Attributes & Events

All spans comply with OpenTelemetry semantic conventions extended with enterprise RAG tags:

* **Session & Identity**: `user.id`, `user.role`, `user.clearance`, `session.id`
* **RAG Flow**: `rag.question`, `rag.response`, `rag.source_count`, `rag.processing_time_ms`
* **MCP / Tools**: `mcp.tool_name`, `mcp.status`, `mcp.duration_ms`
* **HTTP Spans**: `http.method`, `http.url`, `http.status_code`, `http.duration_ms`
* **Events Recorded**:
  * `query_received`: Logged on initial request reception.
  * `retrieval_completed`: Logged with document IDs and vector distance scores.
  * `generation_completed`: Logged upon final output synthesis.

---

## 3. Cross-Service Instrumentation

### 3.1. Core Observability Engine (`app/observability.py`)

A centralized tracing manager handles provider lifecycle, gracefully defaulting to a `NoOpTracer` if Jaeger is unavailable.

```python
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
import time
from typing import Dict, Any, Optional

def setup_observability(service_name: str = "enterprise-rag") -> trace.Tracer:
    """Configures OpenTelemetry tracer provider with OTLP gRPC export."""
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    try:
        processor = BatchSpanProcessor(OTLPSpanExporter(endpoint="localhost:4317", insecure=True))
        provider.add_span_processor(processor)
    except Exception:
        pass
    trace.set_tracer_provider(provider)
    return trace.get_tracer(service_name)

def record_chat_interaction(
    tracer: trace.Tracer,
    user_id: str,
    user_role: str,
    question: str,
    response: str,
    sources: list,
    duration_ms: float
):
    """Generates a dedicated parent span recording full RAG query/response context."""
    with tracer.start_as_current_span("chat_interaction") as span:
        span.set_attribute("user.id", user_id)
        span.set_attribute("user.role", user_role)
        span.set_attribute("rag.question", question)
        span.set_attribute("rag.response", response)
        span.set_attribute("rag.source_count", len(sources))
        span.set_attribute("rag.processing_time_ms", duration_ms)
        span.add_event("query_processed", {
            "sources": str([s.get("source", "unknown") for s in sources])
        })

def record_mcp_tool_execution(
    tracer: trace.Tracer,
    tool_name: str,
    arguments: Dict[str, Any],
    result: Any,
    duration_ms: float,
    status: str = "success"
):
    """Emits spans for Model Context Protocol (MCP) tool calls."""
    with tracer.start_as_current_span(f"mcp_tool:{tool_name}") as span:
        span.set_attribute("mcp.tool_name", tool_name)
        span.set_attribute("mcp.status", status)
        span.set_attribute("mcp.duration_ms", duration_ms)
        span.set_attribute("mcp.args", str(arguments))
        span.add_event("tool_completed", {"result_preview": str(result)[:200]})
```

### 3.2. FastAPI HTTP Middleware & Tracing (`app/main.py`)

Every inbound HTTP request to FastAPI generates a traced span:

```python
import time
from fastapi import FastAPI, Request
from app.observability import setup_observability

app = FastAPI(title="Enterprise RAG Service")
tracer = setup_observability("rag-fastapi")

@app.middleware("http")
async def trace_requests(request: Request, call_next):
    start_time = time.time()
    with tracer.start_as_current_span(f"http_{request.method}_{request.url.path}") as span:
        span.set_attribute("http.method", request.method)
        span.set_attribute("http.url", str(request.url))
        try:
            response = await call_next(request)
            span.set_attribute("http.status_code", response.status_code)
            return response
        except Exception as exc:
            span.record_exception(exc)
            span.set_attribute("http.status_code", 500)
            raise exc
        finally:
            span.set_attribute("http.duration_ms", (time.time() - start_time) * 1000)
```

### 3.3. FastMCP Gateway Tracing (`app/mcp/gateway.py`)

Each tool execution within the MCP server is wrapped with span capture:

```python
import time
from app.observability import setup_observability, record_mcp_tool_execution

mcp_tracer = setup_observability("rag-mcp-server")

async def execute_tool_wrapper(tool_name: str, **kwargs):
    start_time = time.time()
    status = "success"
    try:
        result = await dispatch_tool(tool_name, **kwargs)
        return result
    except Exception as exc:
        status = "error"
        raise exc
    finally:
        duration_ms = (time.time() - start_time) * 1000
        record_mcp_tool_execution(
            tracer=mcp_tracer,
            tool_name=tool_name,
            arguments=kwargs,
            result=result if status == "success" else None,
            duration_ms=duration_ms,
            status=status
        )
```

---

## 4. Persistent Jaeger Storage Architecture

### 4.1. Problem & Root Cause

By default, the Jaeger `all-in-one` image uses an in-memory storage engine. When the Docker container restarts or rebuilds, all stored trace timelines are permanently purged.

Switching to `SPAN_STORAGE_TYPE=badger` enables Badger (an embedded, persistent key-value store using a Log-Structured Merge-tree architecture). However, running this inside Docker frequently triggers a fatal permission error:

> `{"level":"fatal","caller":"all-in-one/main.go:105","msg":"Failed to init storage factory","error":"Error Creating Dir: \"/badger/key\" err: mkdir /badger/key: permission denied"}`

**Root Cause**: The Jaeger container defaults to running as a non-root user (`jaeger`, UID `10001`), which lacks write permissions to host-mounted Docker named volumes root directory `/badger`.

### 4.2. Production `docker-compose.yml` Solution

Declare `user: "0:0"` (root permissions inside container) and map the Badger directory to a persistent named volume:

```yaml
version: "3.8"

services:
  jaeger:
    image: jaegertracing/all-in-one:latest
    container_name: jaeger
    user: "0:0"
    environment:
      - SPAN_STORAGE_TYPE=badger
      - BADGER_EPHEMERAL=false
      - BADGER_DIRECTORY_VALUE=/badger/data
      - BADGER_DIRECTORY_KEY=/badger/key
    ports:
      - "16686:16686" # Web UI
      - "4317:4317"   # OTLP gRPC Ingestion
      - "4318:4318"   # OTLP HTTP Ingestion
      - "14268:14268" # jaeger.thrift ingestion
    volumes:
      - jaeger_data:/badger
    restart: unless-stopped

  postgres:
    image: pgvector/pgvector:pg16
    container_name: enterprise-rag-db
    environment:
      POSTGRES_USER: rag_user
      POSTGRES_PASSWORD: rag_password
      POSTGRES_DB: enterprise_rag
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    restart: unless-stopped

volumes:
  jaeger_data:
    driver: local
  pgdata:
    driver: local
```

> [!TIP]
> **Jaeger v2 Image Naming**: The Docker image `jaegertracing/jaeger:2` is not published under that tag on Docker Hub. Use `jaegertracing/all-in-one:latest` (or official release tags such as `v1.76.0`) for standard local deployments.

---

## 5. Critical Bugs Fixed & Root Cause Analysis

### 5.1. Concurrency: `RuntimeError: Event loop is closed`

* **Symptom**: Repeated requests in Streamlit crashed with:
  `RuntimeError: Event loop is closed` at `openai/_base_client.py:1532`.
* **Root Cause**: An `AsyncOpenAI` client was declared as a global singleton at module import time in `app/db/llm.py`. Streamlit runs user interactions across varying thread pools. When a thread terminates its asyncio event loop, the global client's internal HTTPX connection pool retains references to the destroyed loop, triggering an immediate crash on subsequent calls.
* **Resolution**: Implemented thread/loop-scoped client management via `get_openai_client()`:

```python
import asyncio
from openai import AsyncOpenAI
from typing import Dict

_openai_clients: Dict[asyncio.AbstractEventLoop, AsyncOpenAI] = {}

def get_openai_client() -> AsyncOpenAI:
    """Returns an AsyncOpenAI client bound to the current thread's active event loop."""
    loop = asyncio.get_running_loop()
    if loop not in _openai_clients:
        _openai_clients[loop] = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
    return _openai_clients[loop]
```

### 5.2. Scope Bug: `NameError: name 'json' is not defined`

* **Symptom**: Chat query submission in Streamlit threw `NameError: name 'json' is not defined` inside `streamlit_app.py`.
* **Root Cause**: `json.dumps()` was invoked during debug metadata extraction without an explicit top-level `import json` statement.
* **Resolution**: Added `import json` to top-level imports in `streamlit_app.py`.

### 5.3. Grounding System Prompt Calibration

* **Symptom**: Legitimate questions regarding general repository policies or broad document summaries resulted in abrupt generic refusals: *"I do not have sufficient information in the provided context to answer your question."*
* **Root Cause**: Overly strict prompt penalties caused the model to reject queries when documents didn't match the query wording with 100% lexical precision.
* **Resolution**: Calibrated system prompt to distinguish between *absence of data* and *semantic synthesis of retrieved excerpts*:

```text
You are an enterprise AI assistant for document retrieval and question answering.
Answer the user's question based strictly on the provided context excerpts.
Synthesize information across multiple excerpts if relevant.
Do not speculate or extrapolate beyond the provided text.
If the provided context does not contain any facts relevant to answering the question,
state clearly: "I do not have sufficient information in the provided context to answer your question."
Always cite your sources using the format [Document Name, Page/Section].
```

### 5.4. Dependency Incompatibility

* **Symptom**: `pip install` failures and runtime import errors between FastAPI and OpenTelemetry.
* **Root Cause**: `fastapi==0.142.2` enforces `opentelemetry-api>=1.44.0`, whereas local environment was pinned to an older sub-1.40.0 build.
* **Resolution**: Updated `requirements.txt`:
  ```text
  opentelemetry-api>=1.45.1
  opentelemetry-sdk>=1.45.1
  opentelemetry-exporter-otlp>=1.45.1
  ```

---

## 6. Verification & Operational Runbook

### 6.1. Running the Automated Test Suite

Run unit and integration tests covering RBAC, document chunking, embeddings, vector retrieval, and tracing hooks:

```powershell
pytest -v
```

**Verification Results**:
* Total Tests: **96**
* Passed: **95**
* Skipped: **1** (Live network mock fallback)
* Test Duration: ~18.4s

### 6.2. Container Orchestration & Health Checks

```powershell
# 1. Stop existing containers
docker compose down

# 2. Re-create and start with persistent volumes
docker compose up -d

# 3. Verify container status
docker compose ps
```

Expected Output:
```
NAME                 IMAGE                         STATUS         PORTS
enterprise-rag-db    pgvector/pgvector:pg16        Up (healthy)   0.0.0.0:5432->5432/tcp
jaeger               jaegertracing/all-in-one      Up             0.0.0.0:4317-4318->4317-4318/tcp, 0.0.0.0:16686->16686/tcp
```

### 6.3. Verifying Trace Persistence in Jaeger

1. Open `http://localhost:16686` in a browser.
2. Under **Service**, select `enterprise-rag` or `rag-fastapi`.
3. Submit a query via Streamlit (`http://localhost:8501`) or execute an API call via Swagger (`http://localhost:8000/docs`).
4. Click **Find Traces** in Jaeger UI; inspect the `chat_interaction` span and expand `Tags` to inspect `rag.question` and `rag.response`.
5. Restart the Jaeger container:
   ```powershell
   docker compose restart jaeger
   ```
6. Refresh `http://localhost:16686` and re-run search. **All previous traces remain intact and searchable from Badger disk storage.**

---

## 7. Disclaimer

> [!CAUTION]
> **Data Security & Synthetic Assets**:
> * All test documents, corporate financial summaries, and account figures referenced within this repository and test suite are **synthetic mock assets** generated solely for technical evaluation of Role-Based Access Control (RBAC) and vector similarity search.
> * None of the indexed texts contain genuine Personally Identifiable Information (PII) or authentic material financial records.
> * Always ensure telemetry scrubbers are enabled in enterprise production environments to redact sensitive tokens, authorization headers, and restricted document fragments prior to exporting spans to centralized tracing collectors.
