# Enterprise RAG Microservice 🔐🤖

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100+-009688.svg)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-336791.svg)
![Docker](https://img.shields.io/badge/Docker-Enabled-2496ED.svg)

A production-ready Retrieval-Augmented Generation (RAG) microservice designed for enterprise environments. This project demonstrates how to securely bridge Large Language Models with private organizational data by enforcing **Zero-Trust Role-Based Access Control (RBAC)** at the database layer, combined with highly efficient vector search optimizations.

## 🏗 Architecture Blueprint

![Architecture Diagram](https://raw.githubusercontent.com/Kenono2000/enterprise-rag-pgvector-rbac/main/Architecture%20Blueprint%20%20Secure%20Enterprise%20RAG%20Microservice%20(pgvector%20%2B%20Matryoshka%20%2B%20Zero-Trust%20RBAC).drawio.svg)

## ✨ Key Features

* **Hard Data Isolation (RBAC):** Row-level security and access control enforced directly at the PostgreSQL layer using JSONB queries `WHERE allowed_roles ?| ARRAY[claims.roles]`.
* **Matryoshka Embedding Truncation:** Optimizes storage and compute by dynamically truncating 1536-dimensional embeddings without sacrificing retrieval accuracy.
* **HNSW Vector Indexing:** Utilizes `pgvector` with Hierarchical Navigable Small World (HNSW) indexes for sub-millisecond semantic similarity search.
* **Strict Data Contracts:** Built on FastAPI with Pydantic Data Transfer Objects (DTOs) to guarantee structured, deterministic inputs and outputs.
* **Dockerized Infrastructure:** Containerized PostgreSQL environment with `pgvector` pre-configured for immediate deployment.

## 📂 Core Project Structure

```text
.
├── app/
│   ├── client.py        # FastAPI routing and strict Pydantic DTO schema contracts
│   ├── database.py      # SQL execution (CREATE EXTENSION vector, JSONB role filtering)
│   └── retriever.py     # Embedding generation and Matryoshka truncation logic
├── docker-compose.yml   # PostgreSQL + pgvector infrastructure
└── main.py              # Application entry point
