# Enterprise Zero-Trust RAG Microservice 🛡️

[![Streamlit App](https://static.streamlit.io/badges/streamlit_badge_black_white.svg)](https://enterprise-rag-pgvector-rbac.streamlit.app)
[![Python](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg?logo=fastapi)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg?logo=postgresql)](https://www.postgresql.org/)
[![pgvector](https://img.shields.io/badge/pgvector-Supported-success.svg)](https://github.com/pgvector/pgvector)
[![Auth0](https://img.shields.io/badge/Auth0-Secured-EB5424.svg?logo=auth0)](https://auth0.com/)

**High-Throughput Retrieval-Augmented Generation with In-Database RBAC & pgvector**  
**Architect:** Ken Wong | [Connect on LinkedIn](https://linkedin.com/in/kenwong-architect)

---

> 🚀 **Interactive Live Demo:**  
> Test the Zero-Trust Shift-Left RBAC filtering in real-time directly in your browser:  
> **[👉 Launch Live Demo on Streamlit](https://enterprise-rag-pgvector-rbac.streamlit.app)**

---

## 🏛️ Architecture Blueprint

![Zero-Trust Enterprise AI Architecture Blueprint](THE%20ZERO-TRUST%20ENTERPRISE%20AI%20ARCHITECTURE%20BLUEPRINT.drawio.svg)

---

## 🔑 Core Problem Solved

Standard RAG (Retrieval-Augmented Generation) architectures often retrieve sensitive context chunks and filter user permissions in application memory. In multi-tenant enterprise environments, this creates severe data-leakage and compliance risks. 

This reference architecture solves this by implementing **Shift-Left Security**:

* 🔐 **Auth0 Identity Integration:** Extracts validated JWT claims (roles, tenant ID) via OAuth 2.0 PKCE.
* 🗄️ **In-Database RBAC Filtering:** Passes JWT roles directly into PostgreSQL using the JSONB existence operator (`?|`). This ensures the database *only* returns authorized chunks during the HNSW vector search—unauthorized data never enters application memory.
* 🗜️ **Matryoshka Truncation (1536d):** Compresses 3072d vectors down to 1536d to respect `pgvector`'s 2000-dimension HNSW indexing ceiling, while retaining >98% semantic accuracy.
* 📄 **Deterministic API Contracts:** Synthesizes LLM responses into strongly-typed Pydantic DTOs, featuring grounded citations and cosine confidence scores.

---

## 🛠️ Technology Stack

* **API Gateway:** Python (FastAPI, Pydantic)
* **Vector Database:** PostgreSQL 16 + `pgvector` (HNSW Cosine Indexing)
* **Identity & Access Management:** Auth0 (OAuth 2.0 / PKCE / JWT Scopes)
* **Frontend Demo:** Streamlit Cloud
* **Orchestration:** Asynchronous Non-Blocking I/O

---

## 📂 Project Structure

```text
enterprise-rag-pgvector-rbac/
├── docker-compose.yml       # Runs PostgreSQL 16 with pgvector extension
├── init.sql                 # DDL schema, HNSW index & sample enterprise data
├── requirements.txt         # Python dependencies
├── main.py                  # FastAPI microservice (RBAC + Matryoshka + RAG)
└── app.py                   # Streamlit live interactive demo dashboard
