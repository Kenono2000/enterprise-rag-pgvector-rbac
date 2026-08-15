# enterprise-rag-pgvector-rbac

Architecture Diagram:
https://github.com/Kenono2000/enterprise-rag-pgvector-rbac/blob/main/Architecture%20Blueprint%20%20Secure%20Enterprise%20RAG%20Microservice%20(pgvector%20%2B%20Matryoshka%20%2B%20Zero-Trust%20RBAC).drawio.svg

docker-compose.yml containing PostgreSQL with pgvector enabled.

Core Files:
app/client.py (FastAPI + Pydantic schema contracts).
app/database.py (SQL script with CREATE EXTENSION IF NOT EXISTS vector and JSONB queries).
app/retriever.py (Matryoshka embedding truncation logic).

Quickstart Section:
docker compose up -d and uvicorn main:app --reload.
