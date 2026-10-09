---
name: zero-trust-rbac-coding
description: Productivity and security skill for authoring in-database Zero-Trust pgvector RBAC queries and schema changes in PostgreSQL.
---

# In-Database Zero-Trust RBAC & Vector Engineering

## When to Use
- Writing or modifying SQL queries involving `documents` or `document_chunks`.
- Writing vector similarity search queries using pgvector (`<=>` cosine distance).
- Modifying database schemas, GIN indices, or HNSW vector indices in `schema.sql` or `app/db/`.

## Anti-Pattern to Avoid (Recall Starvation & Memory Leaks)
❌ **NEVER post-filter permissions in Python memory:**
```python
# FORBIDDEN: Fetches top-k indiscriminately, leaks restricted data into RAM, starves recall
results = await db.fetch("SELECT * FROM chunks ORDER BY embedding <=> $1 LIMIT 10", vec)
authorized = [r for r in results if user_role in r["allowed_roles"]]
```

## Standard In-Database Zero-Trust Pattern
✅ **ALWAYS filter in PostgreSQL before distance calculation:**
```sql
SELECT 
    c.id,
    c.content,
    c.metadata,
    1 - (c.embedding <=> $1) AS similarity_score
FROM document_chunks c
JOIN documents d ON c.document_id = d.id
WHERE d.allowed_roles ?| $2::text[]   -- GIN index pre-filter via jsonb_path_ops
ORDER BY c.embedding <=> $1            -- HNSW vector cosine search
LIMIT $3;
```

## Checklist for New Database Operations
1. **Roles Array**: Ensure user roles are passed as a PostgreSQL text array (`$2::text[]`) or JSONB string array.
2. **Indexing**:
   - `allowed_roles` MUST use a `GIN` index (`USING gin (allowed_roles jsonb_path_ops)`).
   - `embedding` MUST use an `HNSW` index (`USING hnsw (embedding vector_cosine_ops)`).
3. **Deterministic Dimension**:
   - Vector dimension must always strictly be `vector(1536)` (matching `text-embedding-3-large`).
