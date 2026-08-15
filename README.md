# Enterprise Zero-Trust RAG Microservice
### High-Throughput Retrieval-Augmented Generation with In-Database RBAC & pgvector
**Architect:** Ken Wong | [LinkedIn](https://linkedin.com/in/kenwong-architect)

---

## 🏛️ Architecture Blueprint

![Zero-Trust Enterprise AI Architecture Blueprint](THE%20ZERO-TRUST%20ENTERPRISE%20AI%20ARCHITECTURE%20BLUEPRINT.drawio.svg)

---

## 🔑 Core Problem Solved

Standard RAG architectures retrieve sensitive context chunks and filter user permissions in application memory, creating data-leakage and compliance risks in multi-tenant enterprise environments.

This reference architecture implements **Shift-Left Security**:
* **Auth0 Identity Integration:** Extracts validated JWT claims (roles, tenant ID) via OAuth 2.0 PKCE.
* **In-Database RBAC Filtering:** Passes JWT roles directly into PostgreSQL using the JSONB existence operator (`?|`), ensuring the database only returns authorized chunks during the HNSW vector search.
* **Matryoshka Truncation (1536d):** Compresses 3072d vectors to 1536d to respect `pgvector`'s 2000-dimension HNSW indexing ceiling while retaining >98% semantic accuracy.
* **Deterministic API Contracts:** Synthesizes LLM responses into typed Pydantic DTOs with grounded citations and cosine confidence scores.

---

## 🛠️ Technology Stack
* **API Gateway:** Python (FastAPI, Pydantic)
* **Vector Database:** PostgreSQL 16 + `pgvector` (HNSW Cosine Indexing)
* **Identity & Access Management:** Auth0 (OAuth 2.0 / PKCE / JWT Scopes)
* **Orchestration:** Asynchronous Non-Blocking I/O
