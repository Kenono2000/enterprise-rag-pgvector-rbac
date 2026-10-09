---
name: test-automation-and-tdd
description: Productivity skill for writing, mocking, and running tests in enterprise-rag-pgvector-rbac using pytest, asyncio, and database/LLM mocks.
---

# Test Automation & TDD Workflow

## When to Use
- Writing new unit tests, integration tests, or regression test suites in `tests/`.
- Mocking PostgreSQL/asyncpg connections, OpenAI embeddings, or JWT authentication headers.
- Debugging failing tests or testing RBAC security isolation.

## Core Rules for This Codebase
1. **Async Tests**: Always annotate async test functions with `@pytest.mark.asyncio`.
2. **Fast Mocking over Heavy DB**:
   - For unit tests, mock `asyncpg.Pool` and `asyncpg.Connection` rather than requiring a live PostgreSQL instance.
   - Mock embedding API calls (`text-embedding-3-large`) with deterministic 1536-dimensional mock vectors.
3. **RBAC Isolation Tests**:
   - Always write tests asserting that unauthorized roles receive `[]` (empty list) or 403 Forbidden.
   - Test boundary conditions: empty roles list, invalid JWT signatures, expired tokens.

## Running Tests Quickly
```bash
# Run full suite
pytest

# Run targeted test file
pytest tests/test_rbac.py -v

# Run only RBAC or security tests
pytest -k "rbac or security or token" -v

# Run with short tracebacks for rapid iteration
pytest --tb=short -q
```

## Standard Fixture Patterns
- **User Claims Fixture**: Provide sample decoded tokens with `sub`, `email`, and `roles: ["admin", "analyst"]`.
- **Mock DB Cursor**: Provide `fetch`, `fetchrow`, `execute` AsyncMocks returning JSONB role structures matching `schema.sql`.
