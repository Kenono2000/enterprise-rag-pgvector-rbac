# 🛡️ Enterprise Zero-Trust RAG Microservice

**High-Throughput Retrieval-Augmented Generation with In-Database RBAC & `pgvector`**

**Architect:** [Ken Wong](https://www.linkedin.com/in/ken-wong)  
**Target Stack:** Python, FastAPI, PostgreSQL, `pgvector`, FastMCP, Auth0

---

## 🚀 Live Interactive Demos

> ⚠️ **Note on Demos vs. Production:** The Streamlit UI (`app.py`) uses a lightweight, mocked dataset to allow zero-friction local demonstration of the RBAC filtering logic. However, the core microservice (`main.py`) is a **production-grade, real vector database implementation** designed for enterprise deployment (see [Real Vector DB Implementation](#-real-vector-database--indexed-rag-implementation) below).

- **🎨 Visual UI Demo (Mocked Data):** Test the Shift-Left RBAC filtering in a user-friendly interface:  
  👉 **[Launch Live Streamlit Demo](#-real-vector-database--indexed-rag-implementation)** *(Link to your deployed Streamlit app)*
- **⚡ Live API & Swagger UI:** Test the raw, production-ready microservice endpoints:  
  👉 **[https://enterprise-rag-api-ksez.onrender.com/docs](https://enterprise-rag-api-ksez.onrender.com/docs)**
- **🤖 Live AI Agent Endpoint:** Connect your MCP client to our secure SSE gateway:  
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
