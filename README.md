# enterprise-rag-pgvector-rbac

# Architecture Blueprint: Secure Enterprise RAG Microservice (pgvector + Matryoshka + Zero-Trust RBAC)
An enterprise architectural breakdown solving vector database scaling and compliance challenges in FinTech. Covers logarithmic HNSW retrieval, Matryoshka dimensionality reduction (truncating 3072d to 1536d to respect hardware constraints), and in-database JSONB RBAC filtering (?|) against Auth0 JWT claims to eliminate multi-tenant data leakage.

[ Client / Web App ] 
        │
        │ 1. Bearer JWT (Auth0 PKCE)
        ▼
[ FastAPI Gateway (Pydantic DTO) ]
        │
        │ 2. Embed Query (Matryoshka Truncation -> 1536d)
        ▼
[ PostgreSQL / pgvector ] ◄── 3. WHERE allowed_roles ?| ARRAY[claims.roles]
  • HNSW Index Search
  • Hard Isolation at DB Layer
        │
        │ 4. Grounded, Authorized Chunks
        ▼
[ LLM Inference (Ollama / Claude / GPT) ]
        │
        │ 5. Structured Output (Answer + Citations + Confidence Score)
        ▼
[ Client Application ]
