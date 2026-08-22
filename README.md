# Enterprise Zero-Trust RAG Microservice 🛡️

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://enterprise-rag-pgvector-rbac.streamlit.app)
[![MCP Ready](https://img.shields.io/badge/MCP-Agent--Ready-purple?logo=modelcontextprotocol)](https://modelcontextprotocol.io)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![pgvector](https://img.shields.io/badge/Database-pgvector-336791?logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)

**High-Throughput Retrieval-Augmented Generation with In-Database RBAC & pgvector**  
**Architect:** Ken Wong | [Connect on LinkedIn](https://linkedin.com/in/kenwong-architect)

---

> 🚀 **Interactive Live Demo:**  
> Test the Zero-Trust Shift-Left RBAC filtering in real-time directly in your browser:  
> **[👉 Launch Live Demo on Streamlit](https://enterprise-rag-pgvector-rbac.streamlit.app)**

---

## 🏛️ Architecture Blueprint

sequenceDiagram
    participant User as AI Agent / Client
    participant API as FastAPI (main.py)
    participant DB as PostgreSQL + pgvector
    participant LLM as OpenAI (gpt-4o)

    User->>API: POST /api/v1/query (Question + JWT Roles)
    API->>API: Generate 1536d Matryoshka Embedding
    API->>DB: Query with `?|` JSONB Role Filter + Vector Search
    DB-->>API: Return ONLY Authorized Chunks (Shift-Left Security)
    API->>LLM: Synthesize Answer with Grounded Context
    LLM-->>API: Deterministic JSON Response
    API-->>User: RAGResponse (Answer + Citations + Confidence)

---

## 🔑 Core Problem Solved

Standard RAG (Retrieval-Augmented Generation) architectures often retrieve sensitive context chunks and filter user permissions in application memory. In multi-tenant enterprise environments, this creates severe data-leakage and compliance risks. 

This reference architecture solves this by implementing **Shift-Left Security**:

* 🔐 **Auth0 Identity Integration:** Extracts validated JWT claims (roles, tenant ID) via OAuth 2.0 PKCE.
* 🗄️ **In-Database RBAC Filtering:** Passes JWT roles directly into PostgreSQL using the JSONB existence operator (`?|`). This ensures the database *only* returns authorized chunks during the HNSW vector search—unauthorized data never enters application memory.
* 🗜️ **Matryoshka Truncation (1536d):** Compresses 3072d vectors down to 1536d to respect `pgvector`'s 2000-dimension HNSW indexing ceiling, while retaining >98% semantic accuracy.
* 🤖 **Agent-Ready MCP Server:** Implements the Model Context Protocol (MCP) via `fastmcp`, allowing AI Agents to perform secure, tool-based retrieval with identity-aware filtering.
* 📄 **Deterministic API Contracts:** Synthesizes LLM responses into strongly-typed Pydantic DTOs, featuring grounded citations and cosine confidence scores.

---

## 🛠️ Technology Stack

* **AI Agent Protocol:** Model Context Protocol (MCP)
* **API Gateway:** Python (FastAPI, Pydantic)
* **Vector Database:** PostgreSQL 16 + `pgvector` (HNSW Cosine Indexing)
* **Identity & Access Management:** Auth0 (OAuth 2.0 / PKCE / JWT Scopes)
* **Frontend Demo:** Streamlit Cloud
* **Orchestration:** Asynchronous Non-Blocking I/O

---

## 🤖 AI Agent Integration (MCP)

This project is "Agent-Ready." It includes a Model Context Protocol (MCP) server that allows AI agents (like Claude Desktop) to interact with the secure RAG engine as a tool.

### Features:
- **Tools:** `search_knowledge_base(question, user_role)` - Allows agents to query the DB with a specific role identity.
- **Resources:** 
    - `security://rbac-policy`: Explains the active security rules to the agent.
    - `system://manifest`: Provides a high-level overview of available documentation.

### How to use with Claude Desktop:
1. Add this to your `claude_desktop_config.json`:
```json
{
  "mcpServers": {
    "zero-trust-rag": {
      "command": "python",
      "args": ["/path/to/enterprise-rag-pgvector-rbac/mcp_server.py"]
    }
  }
}
```
2. Restart Claude Desktop.
3. Ask Claude: *"Search the knowledge base for Q3 margins using the finance_executive role."*

---


## 📂 Project Structure

```text
enterprise-rag-pgvector-rbac/
├── docker-compose.yml       # Runs PostgreSQL 16 with pgvector extension
├── init.sql                 # DDL schema, HNSW index & sample enterprise data
├── requirements.txt         # Python dependencies
├── main.py                  # FastAPI microservice (RBAC + Matryoshka + RAG)
├── mcp_server.py            # Model Context Protocol (MCP) server for AI Agents
└── app.py                   # Streamlit live interactive demo dashboard
