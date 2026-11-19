"""
app/memory/__init__.py
----------------------
Free, self-hosted shared chat + agent memory layer.

Zero new dependencies: persists shared chat threads/messages and cross-agent
facts in the project's existing PostgreSQL + pgvector database, with an
optional ChromaDB semantic accelerator (already installed). Every read and
write is pre-filtered by the canonical fail-closed RBAC contract
(``app.auth.role_mapper.sanitize_roles_for_query``) so the shared memory
inherits the same zero-trust invariants as document retrieval.

Exports:
    SharedMemoryStore  — pgvector-backed shared chat + agent memory store
    MemoryChatRequest / MemoryRecallRequest / MemoryFactRequest — strict schemas
"""

from app.memory.store import (
    SharedMemoryStore,
    MemoryChatRequest,
    MemoryRecallRequest,
    MemoryFactRequest,
    MemoryChatResponse,
    MemoryRecallResponse,
    MemoryFactResponse,
)

__all__ = [
    "SharedMemoryStore",
    "MemoryChatRequest",
    "MemoryRecallRequest",
    "MemoryFactRequest",
    "MemoryChatResponse",
    "MemoryRecallResponse",
    "MemoryFactResponse",
]
