---
name: enterprise-rag-skill
description: A project-specific skill for enterprise-rag-pgvector-rbac, covering RAG pipelines, pgvector indexing, and RBAC security rules.
---

# Enterprise RAG with pgvector & RBAC

## Overview
Guidelines and standard workflows for developing, querying, and testing the enterprise RAG application with PostgreSQL pgvector and Role-Based Access Control (RBAC).

## When to Use
- Working with vector embeddings, similarity search, or pgvector indexing.
- Implementing or modifying RBAC permission checks, tenant isolation, or role policies.
- Building or updating RAG retrieval pipelines, document ingestion, and chunking strategies.

## When NOT to Use
- Generic tasks unrelated to the enterprise RAG or security model.

## Instructions & Workflow
1. **Database & Vector Search**:
   - Verify PostgreSQL connection and pgvector extension status (`CREATE EXTENSION IF NOT EXISTS vector;`).
   - Use cosine distance (`<=>`) or L2 distance (`<->`) matching the embedding model specification.
   - Ensure vector dimension matches the embedding model.
2. **RBAC & Security**:
   - Always enforce tenant/user role filtering in vector retrieval queries.
   - Verify permissions before returning document chunks.
3. **Ingestion & Pipeline**:
   - Maintain consistent chunking strategies and metadata extraction.

## Guidelines & Constraints
- Never bypass RBAC checks during similarity search queries.
- Ensure appropriate indexes (e.g., HNSW or IVFFlat) are used for pgvector columns on large datasets.
