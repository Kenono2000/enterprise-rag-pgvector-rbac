---
name: fastapi-async-architecture
description: Productivity skill for developing high-throughput FastAPI routes, asyncpg connection pooling, Pydantic schemas, and JWT dependencies.
---

# FastAPI Async Architecture & Backend Conventions

## When to Use
- Adding or refactoring FastAPI endpoints under `app/api/` or `app/main.py`.
- Handling async database connections using `asyncpg`.
- Adding request/response Pydantic models with strict validation.
- Integrating authentication via `get_current_user` or Google JWKS token verification.

## Core Patterns

### 1. Loop-Aware Connection Pooling
- Never create ad-hoc connections per request. Use the shared connection pool initialized at application startup:
```python
from app.db.pool import get_db_pool

@router.post("/query", response_model=QueryResponse)
async def query_rag(
    request: QueryRequest,
    current_user: UserClaims = Depends(get_current_user),
    pool = Depends(get_db_pool)
):
    async with pool.acquire() as conn:
        results = await search_vectors_with_rbac(conn, request.query_embedding, current_user.roles)
    return QueryResponse(results=results)
```

### 2. Strict Pydantic Models
- Use Pydantic v2 conventions (`model_config = ConfigDict(strict=True, from_attributes=True)`).
- Validate vector dimensions, non-empty query strings, and pagination limits (`ge=1, le=100`).

### 3. JWT & Role Extraction
- Always obtain identity and roles through FastAPI dependency injection (`Depends(get_current_user)`).
- Never trust client-supplied role parameters in the query body. Roles must be cryptographically extracted from the verified JWT payload.

### 4. Structured Error Responses
- Use FastAPI `HTTPException` with meaningful error codes:
  - `401 Unauthorized`: Missing, expired, or invalid JWT signature.
  - `403 Forbidden`: Authenticated user lacks required roles.
  - `422 Unprocessable Entity`: Request body validation failure.
