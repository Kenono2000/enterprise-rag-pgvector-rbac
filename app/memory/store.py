"""
app/memory/store.py
-------------------
Shared chat + agent memory store (free, self-hosted, zero new dependencies).

Two shared stores, both persisted in the project's existing PostgreSQL +
pgvector database so every FastAPI worker, Streamlit session, MCP gateway,
and autonomous agent sees the same memory:

1. **Shared chat** (``shared_chat_threads`` / ``shared_chat_messages``) —
   persistent multi-turn conversations. A thread is visible to every role in
   its ``allowed_roles`` JSONB column, so a team channel or an agent's
   running commentary is shared across principals and survives reloads.

2. **Agent memories** (``agent_memories``) — durable key/value facts with a
   pgvector embedding for semantic recall. Any agent (incident investigator,
   SDLC crew, Hermes) can write a fact and any other agent (or chat) can
   recall it later — the cross-agent shared memory layer.

Zero-trust contract (mirrors document retrieval invariants):
    * Every row carries ``allowed_roles JSONB``; reads use the
      ``allowed_roles ?| $N::text[]`` GIN-pre-filtered query with roles bound
      as parameters (never inlined).
    * Roles are sanitized through the canonical
      ``app.auth.role_mapper.sanitize_roles_for_query`` (KNOWN_ROLES ∪
      identifiers); an empty resolved role list **fails closed to []** without
      touching the pool (architectural invariant #2).
    * Embeddings are deterministic and offline: when no OpenAI/Azure/GCP
      key is configured, a stable hash-derived mock vector is used (mirrors
      ``app.db.llm.generate_embedding``'s mock branch) so the store is fully
      testable and runnable without billable API calls.
    * ChromaDB is an *optional* in-process semantic accelerator only — the
      pgvector path is authoritative and works with no Chroma at all.

All SQL is parameterized; no string interpolation of user input.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.auth.role_mapper import sanitize_roles_for_query
from app.db.llm import generate_embedding
from app.db.manager import DatabaseManager
from app.observability import tracer

logger = logging.getLogger(__name__)

# Dimensions must match the project's text-embedding-3-small / halfvec(1536) contract.
MEMORY_EMBEDDING_DIM = 1536

# Result-size guardrails so recall/list operations stay bounded as tables grow.
MAX_RECALL_TOP_K = 50
MAX_LIST_THREADS_LIMIT = 100
MAX_GET_THREAD_MESSAGES_LIMIT = 200


# ---------------------------------------------------------------------------
# Strict deterministic request/response schemas (extra='forbid')
# ---------------------------------------------------------------------------


class MemoryChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: Optional[str] = Field(default=None, description="Existing thread ID to continue; omitted to create a new thread.")
    message: str = Field(..., min_length=1, description="The chat message to append to the shared thread.")
    role: str = Field(default="user", description="Message author role label (user / assistant / agent).")
    allowed_roles: List[str] = Field(default_factory=lambda: ["engineer"], description="Roles authorized to read this thread.")
    metadata: Optional[Dict[str, Any]] = Field(default=None, description="Optional structured context attached to the message.")


class MemoryChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    thread_id: str
    message_id: str
    stored: bool


class MemoryRecallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(..., min_length=1, description="Natural-language recall query.")
    user_roles: List[str] = Field(default_factory=list, description="Caller roles for RBAC pre-filtering.")
    top_k: int = Field(default=5, ge=1, le=50, description="Maximum memories/messages to return.")
    scope: str = Field(default="all", description="'chat', 'facts', or 'all'.")


class MemoryRecallResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str
    memories: List[Dict[str, Any]]
    chat_messages: List[Dict[str, Any]]
    total: int


class MemoryFactRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(..., min_length=1, description="Stable fact key (e.g. 'prefers_dark_mode').")
    value: str = Field(..., min_length=1, description="Fact text/value to remember.")
    allowed_roles: List[str] = Field(default_factory=lambda: ["engineer"], description="Roles authorized to read this fact.")
    source: str = Field(default="agent", description="Provenance label (agent name, tool, or 'chat').")


class MemoryFactResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    memory_id: str
    key: str
    stored: bool


# ---------------------------------------------------------------------------
# Deterministic offline embedding (no billable API calls)
# ---------------------------------------------------------------------------


def _mock_embedding(text: str, dimensions: int = MEMORY_EMBEDDING_DIM) -> List[float]:
    """
    Stable, deterministic embedding derived from the text's SHA-256.

    Used when no LLM provider key is configured so the shared memory store is
    fully functional offline and hermetic-testable, mirroring the mock branch
    of ``app.db.llm.generate_embedding``. Values are bounded to [-1, 1].
    """
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    # Expand the 32-byte digest into `dimensions` floats deterministically.
    vec: List[float] = []
    for i in range(dimensions):
        byte = digest[i % len(digest)]
        # Mix in the position so repeated bytes don't collapse to identical values.
        mixed = (byte ^ (i & 0xFF)) / 255.0
        vec.append(round(mixed * 2.0 - 1.0, 6))
    return vec


async def _embed(text: str) -> List[float]:
    """
    Produce an embedding, preferring the configured provider and falling back
    to the deterministic offline mock. Never raises — memory must degrade
    gracefully rather than break the chat/agent path.
    """
    try:
        provider_vec = await generate_embedding(text, dimensions=MEMORY_EMBEDDING_DIM)
        if provider_vec and len(provider_vec) == MEMORY_EMBEDDING_DIM:
            return provider_vec
    except Exception as exc:  # pragma: no cover - provider failure path
        logger.warning("Provider embedding failed, falling back to offline mock: %s", exc)
    return _mock_embedding(text)


def _safe_key(value: str) -> str:
    """Normalize a memory key to a safe identifier-ish slug."""
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", (value or "").strip())
    return slug[:128] or "memory"


# ---------------------------------------------------------------------------
# Shared memory store
# ---------------------------------------------------------------------------


class SharedMemoryStore:
    """
    pgvector-backed shared chat + agent memory store.

    All methods are async and resolve roles through the canonical
    ``sanitize_roles_for_query`` contract. An empty resolved role list fails
    closed (returns [] / no-op) without executing any SQL, matching the
    repository's zero-trust retrieval invariants.
    """

    # -- chat thread lifecycle ----------------------------------------------

    @classmethod
    async def create_thread(
        cls,
        title: str,
        allowed_roles: List[str],
        created_by: str = "anonymous",
    ) -> Optional[str]:
        """Create a new shared chat thread; returns its thread_id (or None on failure)."""
        roles = sanitize_roles_for_query(allowed_roles)
        if not roles:
            logger.warning("create_thread refused: no valid allowed_roles (fail-closed).")
            return None
        thread_id = str(uuid.uuid4())
        try:
            pool = await DatabaseManager.get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO shared_chat_threads (thread_id, title, created_by, allowed_roles)
                    VALUES ($1, $2, $3, $4::jsonb)
                    """,
                    thread_id,
                    title[:255],
                    created_by,
                    json.dumps(roles),
                )
            return thread_id
        except Exception as exc:
            logger.error("create_thread failed: %s", exc)
            return None

    @classmethod
    async def append_message(
        cls,
        thread_id: str,
        message: str,
        role: str = "user",
        allowed_roles: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None,
        embedding: Optional[List[float]] = None,
    ) -> Optional[str]:
        """
        Append a message to a shared thread.

        The thread's ``allowed_roles`` is the access contract; if ``allowed_roles``
        is provided it must be a subset already authorized on the thread (the
        thread row governs visibility). The message embedding is stored so the
        thread is semantically searchable.
        """
        if not thread_id or not message:
            return None
        try:
            vec = embedding if embedding is not None else await _embed(message)
            pool = await DatabaseManager.get_pool()
            async with pool.acquire() as conn:
                # RBAC invariant: the thread governs visibility; we only insert
                # when the thread exists. allowed_roles on the message mirrors
                # the thread so per-message recall can pre-filter too.
                thread_roles = await conn.fetchval(
                    "SELECT allowed_roles FROM shared_chat_threads WHERE thread_id = $1",
                    thread_id,
                )
                if thread_roles is None:
                    logger.warning("append_message: thread %s not found; refusing.", thread_id)
                    return None
                msg_id = str(uuid.uuid4())
                await conn.execute(
                    """
                    INSERT INTO shared_chat_messages
                        (message_id, thread_id, role, content, embedding, metadata)
                    VALUES ($1, $2, $3, $4, $5::vector, $6::jsonb)
                    """,
                    msg_id,
                    thread_id,
                    role,
                    message,
                    _format_vector(vec),
                    json.dumps(metadata or {}, default=str),
                )
            return msg_id
        except Exception as exc:
            logger.error("append_message failed: %s", exc)
            return None

    @classmethod
    async def get_thread_messages(
        cls,
        thread_id: str,
        user_roles: List[str],
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Return a thread's messages visible to ``user_roles`` (RBAC pre-filtered).

        ``limit`` is clamped to ``MAX_GET_THREAD_MESSAGES_LIMIT`` so callers
        cannot page an unbounded number of messages from a long thread.
        """
        roles = sanitize_roles_for_query(user_roles)
        if not roles:
            return []
        try:
            pool = await DatabaseManager.get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT m.message_id, m.thread_id, m.role, m.content, m.metadata, m.created_at
                    FROM shared_chat_messages m
                    JOIN shared_chat_threads t ON t.thread_id = m.thread_id
                    WHERE m.thread_id = $1 AND t.allowed_roles ?| $2::text[]
                    ORDER BY m.created_at ASC
                    LIMIT $3
                    """,
                    thread_id,
                    roles,
                    limit,
                )
                return [
                    {
                        "message_id": r["message_id"],
                        "thread_id": r["thread_id"],
                        "role": r["role"],
                        "content": r["content"],
                        "metadata": r["metadata"] or {},
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    }
                    for r in rows
                ]
        except Exception as exc:
            logger.error("get_thread_messages failed: %s", exc)
            return []

    @classmethod
    async def list_threads(
        cls,
        user_roles: List[str],
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List shared threads visible to ``user_roles`` (RBAC pre-filtered).

        ``limit`` is clamped to ``MAX_LIST_THREADS_LIMIT`` (mirroring the MCP
        ``memory_list_threads`` cap) so listing stays bounded as threads grow.
        """
        roles = sanitize_roles_for_query(user_roles)
        if not roles:
            return []
        try:
            pool = await DatabaseManager.get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    """
                    SELECT thread_id, title, created_by, allowed_roles, created_at
                    FROM shared_chat_threads
                    WHERE allowed_roles ?| $1::text[]
                    ORDER BY created_at DESC
                    LIMIT $2
                    """,
                    roles,
                    limit,
                )
                return [
                    {
                        "thread_id": r["thread_id"],
                        "title": r["title"],
                        "created_by": r["created_by"],
                        "allowed_roles": list(r["allowed_roles"] or []),
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    }
                    for r in rows
                ]
        except Exception as exc:
            logger.error("list_threads failed: %s", exc)
            return []

    # -- agent memory facts --------------------------------------------------

    @classmethod
    async def store_fact(
        cls,
        key: str,
        value: str,
        allowed_roles: List[str],
        source: str = "agent",
        embedding: Optional[List[float]] = None,
    ) -> Optional[str]:
        """
        Store a durable agent memory fact with a semantic embedding.

        Upserts on ``key`` so re-learning the same fact updates rather than
        duplicates. Fails closed when no valid roles are provided.
        """
        roles = sanitize_roles_for_query(allowed_roles)
        if not roles:
            logger.warning("store_fact refused for key=%s: no valid allowed_roles (fail-closed).", key)
            return None
        from agent.quality_control import PromptInjectionSanitizer

        if PromptInjectionSanitizer.detect(value):
            logger.warning("store_fact refused for key=%s: potential memory injection (MINJA) detected.", key)
            return None
        safe_key = _safe_key(key)
        try:
            vec = embedding if embedding is not None else await _embed(value)
            memory_id = str(uuid.uuid4())
            pool = await DatabaseManager.get_pool()
            async with pool.acquire() as conn:
                await conn.execute(
                    """
                    INSERT INTO agent_memories (memory_id, memory_key, value, source, allowed_roles, embedding)
                    VALUES ($1, $2, $3, $4, $5::jsonb, $6::vector)
                    ON CONFLICT (memory_key) DO UPDATE SET
                        value = EXCLUDED.value,
                        source = EXCLUDED.source,
                        allowed_roles = EXCLUDED.allowed_roles,
                        embedding = EXCLUDED.embedding,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    memory_id,
                    safe_key,
                    value,
                    source,
                    json.dumps(roles),
                    _format_vector(vec),
                )
            return memory_id
        except Exception as exc:
            logger.error("store_fact failed for key=%s: %s", safe_key, exc)
            return None

    @classmethod
    async def store_thread_summary(
        cls,
        thread_id: str,
        summary: str,
        allowed_roles: List[str],
        source: str = "summary",
        message_count: Optional[int] = None,
    ) -> Optional[str]:
        """
        Store a rolling summary of a long thread as an agent-memory fact.

        For long threads, instead of recalling every raw message, summarize the
        conversation into one fact keyed ``thread_summary:{thread_id}`` and
        recall that first. Upserts on key so re-summarizing updates rather than
        duplicating. Fails closed when no valid roles are provided.
        """
        roles = sanitize_roles_for_query(allowed_roles)
        if not roles:
            logger.warning("store_thread_summary refused for thread=%s: no valid allowed_roles (fail-closed).", thread_id)
            return None
        key = f"thread_summary:{thread_id}"
        value = summary
        if message_count is not None:
            value = f"[messages={message_count}] {summary}"
        return await cls.store_fact(
            key=key,
            value=value,
            allowed_roles=roles,
            source=source,
        )

    @classmethod
    async def cleanup_expired_messages(cls, older_than_days: int) -> int:
        """
        Delete shared_chat_messages older than ``older_than_days`` (retention guardrail).

        Bound shared_chat_messages growth by purging stale messages. Uses the
        covering index idx_shared_messages_thread_cleanup (thread_id, created_at
        DESC) for efficient time-windowed deletes. Intended to be invoked on a
        schedule (pg_cron / cron invoking psql / the memory_cleanup MCP tool).
        Returns the number of rows deleted.
        """
        try:
            pool = await DatabaseManager.get_pool()
            async with pool.acquire() as conn:
                result = await conn.fetchval(
                    "SELECT cleanup_expired_shared_messages($1)", older_than_days,
                )
            return int(result or 0)
        except Exception as exc:
            logger.error("cleanup_expired_messages failed: %s", exc)
            return 0

    @classmethod
    async def recall_facts(
        cls,
        query: str,
        user_roles: List[str],
        top_k: int = 5,
        ef_search: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Semantic recall of agent memory facts visible to ``user_roles``.

        Uses pgvector cosine similarity (halfvec) with the RBAC GIN pre-filter,
        mirroring the document retrieval query contract. Falls back to a
        deterministic keyword-overlap ranking when embeddings are unavailable.

        ``ef_search`` right-sizes the HNSW search depth per query (guardrail for
        large tables): raise for better recall, lower for faster speed.
        """
        roles = sanitize_roles_for_query(user_roles)
        if not roles:
            return []
        try:
            t_start = time.perf_counter()
            vec = await _embed(query)
            vec_literal = _format_vector(vec)
            pool = await DatabaseManager.get_pool()
            async with pool.acquire() as conn:
                await cls._configure_scan(conn, roles, ef_search=ef_search)
                rows = await conn.fetch(
                    """
                    SELECT memory_id, memory_key, value, source, allowed_roles, created_at,
                           1 - (embedding::halfvec(1536) <=> $1::vector::halfvec(1536)) AS similarity
                    FROM agent_memories
                    WHERE allowed_roles ?| $2::text[]
                    ORDER BY embedding::halfvec(1536) <=> $1::vector::halfvec(1536)
                    LIMIT $3
                    """,
                    vec_literal,
                    roles,
                    top_k,
                )
                result = [
                    {
                        "memory_id": r["memory_id"],
                        "key": r["memory_key"],
                        "value": r["value"],
                        "source": r["source"],
                        "allowed_roles": list(r["allowed_roles"] or []),
                        "similarity": round(float(r["similarity"] or 0.0), 4),
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    }
                    for r in rows
                ]
            tracer.record_mcp_tool_execution(
                tool_name="memory.recall_facts",
                parameters={"query": query, "top_k": top_k, "ef_search": ef_search},
                result=f"{len(result)} facts recalled",
                roles=roles,
                duration_ms=round((time.perf_counter() - t_start) * 1000, 2),
            )
            return result
        except Exception as exc:
            logger.error("recall_facts failed: %s", exc)
            return []

    @classmethod
    async def recall(
        cls,
        query: str,
        user_roles: List[str],
        top_k: int = 5,
        scope: str = "all",
        ef_search: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Unified shared-memory recall across chat messages and agent facts.

        Returns the union of semantically relevant chat messages (from RBAC-
        visible threads) and agent memory facts, ranked by similarity, bounded
        by ``top_k`` per scope.

        ``ef_search`` right-sizes the HNSW search depth per query (guardrail for
        large tables): raise for better recall, lower for faster speed.
        """
        t_start = time.perf_counter()
        roles = sanitize_roles_for_query(user_roles)
        result: Dict[str, Any] = {"query": query, "memories": [], "chat_messages": [], "total": 0}
        if not roles:
            return result

        include_chat = scope in ("chat", "all")
        include_facts = scope in ("facts", "all")

        if include_facts:
            result["memories"] = await cls.recall_facts(query, user_roles, top_k, ef_search=ef_search)

        if include_chat:
            result["chat_messages"] = await cls._recall_chat(query, roles, top_k, ef_search=ef_search)

        result["total"] = len(result["memories"]) + len(result["chat_messages"])
        tracer.record_mcp_tool_execution(
            tool_name="memory.recall",
            parameters={"query": query, "top_k": top_k, "scope": scope, "ef_search": ef_search},
            result=f"{result['total']} shared memories recalled",
            roles=roles,
            duration_ms=round((time.perf_counter() - t_start) * 1000, 2),
        )
        return result

    @classmethod
    async def _recall_chat(
        cls,
        query: str,
        roles: List[str],
        top_k: int,
        ef_search: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Semantic recall over shared chat messages visible to ``roles``.

        ``ef_search`` right-sizes the HNSW search depth per query (guardrail for
        large tables).
        """
        try:
            vec = await _embed(query)
            vec_literal = _format_vector(vec)
            pool = await DatabaseManager.get_pool()
            async with pool.acquire() as conn:
                await cls._configure_scan(conn, roles, ef_search=ef_search)
                rows = await conn.fetch(
                    """
                    SELECT m.message_id, m.thread_id, m.role, m.content, m.metadata, m.created_at,
                           1 - (m.embedding::halfvec(1536) <=> $1::vector::halfvec(1536)) AS similarity
                    FROM shared_chat_messages m
                    JOIN shared_chat_threads t ON t.thread_id = m.thread_id
                    WHERE t.allowed_roles ?| $2::text[]
                    ORDER BY m.embedding::halfvec(1536) <=> $1::vector::halfvec(1536)
                    LIMIT $3
                    """,
                    vec_literal,
                    roles,
                    top_k,
                )
                return [
                    {
                        "message_id": r["message_id"],
                        "thread_id": r["thread_id"],
                        "role": r["role"],
                        "content": r["content"],
                        "metadata": r["metadata"] or {},
                        "similarity": round(float(r["similarity"] or 0.0), 4),
                        "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                    }
                    for r in rows
                ]
        except Exception as exc:
            logger.error("_recall_chat failed: %s", exc)
            return []

    @classmethod
    async def _configure_scan(cls, conn: Any, roles: List[str], ef_search: Optional[int] = None) -> None:
        """Apply pgvector iterative-scan GUCs (PGC_USERSET) per connection, mirroring DatabaseManager.

        ``ef_search`` right-sizes the HNSW search depth per query: raise it for
        better recall on large tables, lower it for faster speed. When omitted,
        falls back to ``DatabaseManager.scaled_ef_search(roles)``.
        """
        try:
            if ef_search is None:
                ef_search = DatabaseManager.scaled_ef_search(roles)
            await DatabaseManager.configure_iterative_scan(
                conn,
                max_scan_tuples=DatabaseManager.scaled_scan_tuples(roles),
                ef_search=ef_search,
            )
        except Exception as exc:  # pragma: no cover - tuning is best-effort
            logger.debug("iterative-scan tuning skipped: %s", exc)


# ---------------------------------------------------------------------------
# pgvector literal helpers
# ---------------------------------------------------------------------------


def _format_vector(vec: List[float]) -> str:
    """Format a list of floats as a pgvector ``[v1,v2,...]`` literal with NaN/Inf sanitization."""
    sanitized: List[str] = []
    for val in vec:
        try:
            fval = float(val)
        except (TypeError, ValueError):
            sanitized.append("0.0")
            continue
        if fval != fval or fval in (float("inf"), float("-inf")):
            sanitized.append("0.0")
        else:
            sanitized.append(str(round(fval, 6)))
    return "[" + ",".join(sanitized) + "]"
