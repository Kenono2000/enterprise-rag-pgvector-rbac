# Enterprise Zero-Trust RAG Microservice 🛡️

**High-Throughput Retrieval-Augmented Generation with In-Database RBAC & pgvector**  
**Architect:** Ken Wong | [LinkedIn](YOUR_LINKEDIN_URL)

[![MCP Ready](https://img.shields.io/badge/MCP-Agent--Ready-purple?logo=modelcontextprotocol)](https://modelcontextprotocol.io)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![pgvector](https://img.shields.io/badge/Database-pgvector-336791?logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![Python 3.11](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)

---

> 🚀 **Live Interactive Demos:**  
> - **⚡ Live API & Swagger UI:** Test the Shift-Left RBAC filtering in real-time:  
>   👉 **[https://enterprise-rag-api.onrender.com/docs](https://enterprise-rag-api.onrender.com/docs)**  
>   *(Try querying with `["finance_executive"]` vs `["public_guest"]` in the `x-user-roles` header!)*
> - **🤖 Live AI Agent Endpoint:** Connect your MCP client (e.g., Prefect Horizon) to our secure SSE gateway:  
>   👉 **`https://enterprise-rag-mcp.onrender.com/sse`**

---

## 🔑 Core Problem Solved

Standard RAG (Retrieval-Augmented Generation) architectures often retrieve sensitive context chunks into application memory and filter user permissions at the API layer. In multi-tenant enterprise environments, this creates severe data-leakage, prompt-injection, and compliance risks (SOC2/GDPR). 

This reference architecture solves this by implementing **Shift-Left Security**:

* 🔐 **Auth0 Identity Integration:** Extracts validated JWT claims (roles, tenant ID) via OAuth 2.0 PKCE.
* 🗄️ **In-Database RBAC Filtering:** Passes JWT roles directly into PostgreSQL using the JSONB existence operator (`?|`). This ensures the database *only* returns authorized chunks during the HNSW vector search—unauthorized data never enters application memory or LLM prompts.
* 🗜️ **Matryoshka Truncation (1536d):** Compresses 3072d vectors down to 1536d to respect `pgvector`'s 2000-dimension HNSW indexing ceiling, retaining >98% semantic accuracy while optimizing storage and query latency.
* 🤖 **Agent-Ready MCP Server:** Implements the Model Context Protocol (MCP) via `fastmcp`, allowing AI Agents to perform secure, tool-based retrieval with identity-aware filtering.
* 📄 **Deterministic API Contracts:** Synthesizes LLM responses into strongly-typed Pydantic DTOs, featuring grounded citations and cosine confidence scores for auditability.

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
    API-->>Agent: RAGResponse (Answer + Citations + Confidence)