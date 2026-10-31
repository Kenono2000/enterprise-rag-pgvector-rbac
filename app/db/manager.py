import os
import struct
import asyncio
import asyncpg
import json
from typing import Optional, List, Dict, Any, Tuple
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(), override=True)


def get_db_url():
    # Priority: OS Env -> Streamlit Secrets
    url = os.getenv("DATABASE_URL")
    if not url:
        try:
            import streamlit as st
            url = st.secrets.get("DATABASE_URL")
        except Exception:
            pass

    if url and url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


class DatabaseManager:
    _pool: Optional[asyncpg.Pool] = None
    _loop: Optional[asyncio.AbstractEventLoop] = None
    HNSW_ITERATIVE_SCAN_MODE: str = os.getenv("PGVECTOR_ITERATIVE_SCAN", "relaxed_order")
    HNSW_MAX_SCAN_TUPLES: int = int(os.getenv("PGVECTOR_MAX_SCAN_TUPLES", "20000"))
    USE_HALFVEC_INDEX: bool = os.getenv("PGVECTOR_USE_HALFVEC", "true").lower() == "true"

    @classmethod
    def format_halfvec(cls, query_vector: List[float], dimensions: int = 1536) -> str:
        """
        Quantize float vector values to IEEE 754 16-bit half-precision (`halfvec(1536)`)
        and serialize into a pgvector literal string `[v1,v2,...]` for 50% RAM compaction.
        """
        quantized: List[str] = []
        for val in query_vector[:dimensions]:
            try:
                f16 = struct.unpack("e", struct.pack("e", float(val)))[0]
                quantized.append(str(round(f16, 6)))
            except (OverflowError, ValueError):
                quantized.append("0.0")
        return f"[{','.join(quantized)}]"

    @classmethod
    async def configure_iterative_scan(
        cls,
        conn: Any,
        mode: Optional[str] = None,
        max_scan_tuples: Optional[int] = None,
    ) -> bool:
        """
        Configure pgvector 0.8+ HNSW iterative index scans on a connection so selective
        RBAC WHERE clauses (`allowed_roles ?| $2::text[]`) never suffer from ANN overfiltering.
        Gracefully returns False on pgvector < 0.8.0.
        """
        scan_mode = (mode or cls.HNSW_ITERATIVE_SCAN_MODE or "relaxed_order").strip()
        if scan_mode not in ("off", "strict_order", "relaxed_order"):
            scan_mode = "relaxed_order"
        tuples_limit = int(max_scan_tuples or cls.HNSW_MAX_SCAN_TUPLES or 20000)
        try:
            await conn.execute(f"SET hnsw.iterative_scan = '{scan_mode}'")
            await conn.execute(f"SET hnsw.max_scan_tuples = {tuples_limit}")
            return True
        except Exception:
            return False

    @classmethod
    def scaled_scan_tuples(cls, roles: List[str]) -> int:
        """
        Scale `hnsw.max_scan_tuples` by role selectivity: narrow callers (1 role) match few rows and
        need deeper graph traversal (2x base); broad callers (3+ roles) stop earlier (base/2, floor 5000).
        """
        base = int(cls.HNSW_MAX_SCAN_TUPLES or 20000)
        count = len({r for r in roles if r})
        if count <= 1:
            return base * 2
        if count == 2:
            return base
        return max(5000, base // 2)

    @classmethod
    async def get_pool(cls) -> asyncpg.Pool:
        # Streamlit may run each script rerun on a different event loop.
        # asyncpg binds connections to the loop they were created on, so a
        # cached pool from a previous (now-closed/different) loop is unusable.
        try:
            current_loop = asyncio.get_event_loop()
        except RuntimeError:
            current_loop = asyncio.new_event_loop()
            asyncio.set_event_loop(current_loop)

        needs_recreate = (
            cls._pool is None
            or cls._loop is None
            or cls._loop is not current_loop
            or cls._loop.is_closed()
        )
        if needs_recreate:
            if cls._pool is not None:
                try:
                    await cls._pool.close()
                except Exception:
                    pass

            db_url = get_db_url()
            if not db_url:
                raise ValueError("❌ DATABASE_URL is not set in Env or Streamlit Secrets")

            # Use SSL if connecting to a cloud provider (common requirement)
            # Most hosted DBs require SSL; 'require' is a safe default for production.
            cls._pool = await asyncpg.create_pool(
                db_url,
                min_size=1,
                max_size=5,
                init=cls.configure_iterative_scan,
                ssl="require" if "localhost" not in db_url else None
            )
            cls._loop = current_loop
        return cls._pool

    @classmethod
    async def close(cls):
        if cls._pool:
            await cls._pool.close()
            cls._pool = None

    @classmethod
    async def secure_search(
        cls,
        query_vector: List[float],
        user_roles: List[str],
        limit: int = 10,
        use_halfvec: Optional[bool] = None,
    ):
        # Zero-Trust: If caller has no roles, return empty results immediately
        if not user_roles:
            return []

        # Defense-in-depth: Ensure all role entries are valid, non-empty identifier strings
        from app.auth.role_mapper import KNOWN_ROLES
        sanitized_roles = [
            str(r).strip() for r in user_roles
            if isinstance(r, str) and (str(r).strip() in KNOWN_ROLES or str(r).strip().isidentifier())
        ]
        if not sanitized_roles:
            return []

        pool = await cls.get_pool()
        halfvec_enabled = cls.USE_HALFVEC_INDEX if use_halfvec is None else use_halfvec
        vector_str = (
            cls.format_halfvec(query_vector)
            if halfvec_enabled
            else f"[{','.join(map(str, query_vector))}]"
        )

        distance_expr = (
            "c.embedding::halfvec(1536) <=> $1::vector::halfvec(1536)"
            if halfvec_enabled
            else "c.embedding <=> $1::vector"
        )
        sql = f"""
            SELECT d.document_id, d.title, c.chunk_index, c.content, d.allowed_roles, 
                   1 - ({distance_expr}) as similarity
            FROM document_chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE d.allowed_roles ?| $2::text[]
              AND (c.embedding_model = 'text-embedding-3-large' OR c.embedding_model IS NULL)
            ORDER BY {distance_expr}
            LIMIT $3
        """
        async with pool.acquire() as conn:
            await cls.configure_iterative_scan(conn, max_scan_tuples=cls.scaled_scan_tuples(sanitized_roles))
            return await conn.fetch(sql, vector_str, sanitized_roles, limit)

    @classmethod
    async def hybrid_search(
        cls,
        query_text: str,
        query_vector: List[float],
        user_roles: List[str],
        limit: int = 10,
        rrf_k: int = 60,
        use_halfvec: Optional[bool] = None,
        dense_weight: float = 1.0,
        sparse_weight: float = 1.0,
    ) -> List[dict]:
        """
        Execute Hybrid Search combining Dense Vector Search (HNSW 16-bit halfvec cosine similarity)
        and Sparse Full-Text Search (GIN tsvector / ts_rank) with Reciprocal Rank Fusion (RRF).
        Supports adaptive dense_weight and sparse_weight to balance semantic vs keyword retrieval.
        Enforces Zero-Trust RBAC: documents outside user_roles are filtered at SQL execution time.
        """
        if not user_roles:
            return []

        from app.auth.role_mapper import KNOWN_ROLES
        sanitized_roles = [
            str(r).strip() for r in user_roles
            if isinstance(r, str) and (str(r).strip() in KNOWN_ROLES or str(r).strip().isidentifier())
        ]
        if not sanitized_roles:
            return []

        pool = await cls.get_pool()
        halfvec_enabled = cls.USE_HALFVEC_INDEX if use_halfvec is None else use_halfvec
        vector_str = (
            cls.format_halfvec(query_vector)
            if halfvec_enabled
            else f"[{','.join(map(str, query_vector))}]"
        )

        dense_dist = (
            "c.embedding::halfvec(1536) <=> $1::vector::halfvec(1536)"
            if halfvec_enabled
            else "c.embedding <=> $1::vector"
        )
        sparse_dist = (
            "c.embedding::halfvec(1536) <=> $2::vector::halfvec(1536)"
            if halfvec_enabled
            else "c.embedding <=> $2::vector"
        )

        # 1. Dense retrieval (HNSW halfvec cosine distance)
        dense_sql = f"""
            SELECT c.id::text as chunk_id_pk, d.document_id, d.title, c.chunk_index, c.content, d.allowed_roles,
                   1 - ({dense_dist}) AS similarity
            FROM document_chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE d.allowed_roles ?| $2::text[]
              AND (c.embedding_model = 'text-embedding-3-large' OR c.embedding_model IS NULL)
            ORDER BY {dense_dist}
            LIMIT $3
        """

        # 2. Sparse retrieval (Full-Text Search with ts_rank and robust fallback)
        sparse_sql = f"""
            SELECT c.id::text as chunk_id_pk, d.document_id, d.title, c.chunk_index, c.content, d.allowed_roles,
                   ts_rank(c.tsv, plainto_tsquery('english', $1)) AS text_rank,
                   1 - ({sparse_dist}) AS similarity
            FROM document_chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE d.allowed_roles ?| $3::text[]
              AND (c.tsv @@ plainto_tsquery('english', $1) OR c.tsv @@ websearch_to_tsquery('english', $1))
            ORDER BY text_rank DESC
            LIMIT $4
        """

        fetch_limit = limit * 2

        # 0. Single-pass SQL RRF: dense + sparse CTEs fused in-database via ROW_NUMBER() window ranks,
        # eliminating cross-network serialization of both candidate sets. Falls back to Python RRF below.
        cte_dist = (
            "c.embedding::halfvec(1536) <=> $1::vector::halfvec(1536)"
            if halfvec_enabled
            else "c.embedding <=> $1::vector"
        )
        fused_sql = f"""
            WITH dense AS (
                SELECT c.id::text AS chunk_id_pk, d.document_id, d.title, c.chunk_index, c.content,
                       d.allowed_roles, 1 - ({cte_dist}) AS similarity,
                       ROW_NUMBER() OVER (ORDER BY {cte_dist}) AS rnk
                FROM document_chunks c
                JOIN documents d ON c.document_id = d.id
                WHERE d.allowed_roles ?| $3::text[]
                  AND (c.embedding_model = 'text-embedding-3-large' OR c.embedding_model IS NULL)
                ORDER BY {cte_dist}
                LIMIT $4
            ),
            sparse AS (
                SELECT c.id::text AS chunk_id_pk, d.document_id, d.title, c.chunk_index, c.content,
                       d.allowed_roles, 1 - ({cte_dist}) AS similarity,
                       ts_rank(c.tsv, plainto_tsquery('english', $2)) AS text_rank,
                       ROW_NUMBER() OVER (ORDER BY ts_rank(c.tsv, plainto_tsquery('english', $2)) DESC) AS rnk
                FROM document_chunks c
                JOIN documents d ON c.document_id = d.id
                WHERE d.allowed_roles ?| $3::text[]
                  AND (c.tsv @@ plainto_tsquery('english', $2) OR c.tsv @@ websearch_to_tsquery('english', $2))
                ORDER BY text_rank DESC
                LIMIT $4
            )
            SELECT COALESCE(dn.chunk_id_pk, sp.chunk_id_pk) AS chunk_id_pk,
                   COALESCE(dn.document_id, sp.document_id) AS document_id,
                   COALESCE(dn.title, sp.title) AS title,
                   COALESCE(dn.chunk_index, sp.chunk_index) AS chunk_index,
                   COALESCE(dn.content, sp.content) AS content,
                   COALESCE(dn.allowed_roles, sp.allowed_roles) AS allowed_roles,
                   COALESCE(dn.similarity, sp.similarity) AS similarity,
                   COALESCE(sp.text_rank, 0.0) AS text_rank,
                   dn.rnk AS dense_rank, sp.rnk AS sparse_rank,
                   COALESCE($5::float8 / ($7::int + dn.rnk), 0.0)
                     + COALESCE($6::float8 / ($7::int + sp.rnk), 0.0) AS rrf_score
            FROM dense dn
            FULL OUTER JOIN sparse sp ON dn.chunk_id_pk = sp.chunk_id_pk
            ORDER BY rrf_score DESC
            LIMIT $8
        """
        try:
            async with pool.acquire() as conn:
                await cls.configure_iterative_scan(conn, max_scan_tuples=cls.scaled_scan_tuples(sanitized_roles))
                fused_rows = await conn.fetch(
                    fused_sql, vector_str, query_text, sanitized_roles, fetch_limit,
                    float(dense_weight), float(sparse_weight), int(rrf_k), limit,
                )
            return [
                {
                    "chunk_id_pk": r["chunk_id_pk"],
                    "document_id": r["document_id"],
                    "title": r["title"],
                    "chunk_index": r["chunk_index"] if r["chunk_index"] is not None else 0,
                    "content": r["content"],
                    "allowed_roles": r["allowed_roles"],
                    "similarity": float(r["similarity"] or 0.0),
                    "text_rank": float(r["text_rank"] or 0.0),
                    "dense_rank": r["dense_rank"],
                    "sparse_rank": r["sparse_rank"],
                    "rrf_score": float(r["rrf_score"]),
                }
                for r in fused_rows
            ]
        except Exception:
            pass  # Fall back to dual-query Python RRF (e.g. missing tsv column or older Postgres)

        async with pool.acquire() as conn:
            await cls.configure_iterative_scan(conn, max_scan_tuples=cls.scaled_scan_tuples(sanitized_roles))
            dense_rows = await conn.fetch(dense_sql, vector_str, sanitized_roles, fetch_limit)
            try:
                sparse_rows = await conn.fetch(sparse_sql, query_text, vector_str, sanitized_roles, fetch_limit)
            except Exception:
                sparse_rows = []

        # 3. Reciprocal Rank Fusion (RRF)
        # RRF Score = sum( weight / (k + rank) )
        candidates = {}

        for rank, row in enumerate(dense_rows):
            key = row["chunk_id_pk"]
            candidates[key] = {
                "chunk_id_pk": key,
                "document_id": row["document_id"],
                "title": row["title"],
                "chunk_index": row.get("chunk_index", 0),
                "content": row["content"],
                "allowed_roles": row["allowed_roles"],
                "similarity": float(row["similarity"]),
                "text_rank": 0.0,
                "dense_rank": rank + 1,
                "sparse_rank": None,
                "rrf_score": float(dense_weight) / (rrf_k + (rank + 1)),
            }

        for rank, row in enumerate(sparse_rows):
            key = row["chunk_id_pk"]
            sparse_score = float(sparse_weight) / (rrf_k + (rank + 1))
            if key in candidates:
                candidates[key]["sparse_rank"] = rank + 1
                candidates[key]["text_rank"] = float(row.get("text_rank", 0.0))
                candidates[key]["rrf_score"] += sparse_score
            else:
                candidates[key] = {
                    "chunk_id_pk": key,
                    "document_id": row["document_id"],
                    "title": row["title"],
                    "chunk_index": row.get("chunk_index", 0),
                    "content": row["content"],
                    "allowed_roles": row["allowed_roles"],
                    "similarity": float(row.get("similarity", 0.0)),
                    "text_rank": float(row.get("text_rank", 0.0)),
                    "dense_rank": None,
                    "sparse_rank": rank + 1,
                    "rrf_score": sparse_score,
                }

        fused = sorted(candidates.values(), key=lambda x: x["rrf_score"], reverse=True)
        return fused[:limit]

    @classmethod
    async def check_readiness(cls) -> dict:
        """Probe database connectivity and vector extension status."""
        pool = await cls.get_pool()
        async with pool.acquire() as conn:
            await conn.execute("SELECT 1")
            ext = await conn.fetchval("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            return {
                "database": "connected",
                "vector_extension": "available" if ext == "vector" else "missing",
            }

    @classmethod
    async def ingest_document(
        cls,
        document_id: str,
        title: str,
        content: str,
        allowed_roles: List[str],
        embedding: List[float],
        file_hash: Optional[str] = None,
    ):
        """Ingest single-chunk document into normalized documents and document_chunks tables."""
        chunks = [
            {
                "chunk_id": f"{document_id}_chunk_1",
                "content": content,
                "embedding": embedding,
            }
        ]
        return await cls.ingest_normalized_document(
            document_id=document_id,
            title=title,
            chunks=chunks,
            allowed_roles=allowed_roles,
            file_hash=file_hash,
        )

    @classmethod
    async def ingest_normalized_document(
        cls,
        document_id: str,
        title: str,
        chunks: List[dict],
        allowed_roles: List[str],
        file_hash: Optional[str] = None,
        source_path: Optional[str] = None,
        file_type: str = "markdown",
    ) -> str:
        """
        Ingest a document and its chunks into normalized documents and document_chunks tables
        with 16-bit `halfvec(1536)` quantization (`embedding_halfvec` generated column).
        Atomic transaction ensures all chunks or none are persisted.
        """
        pool = await cls.get_pool()
        roles_json = json.dumps(allowed_roles)

        async with pool.acquire() as conn:
            async with conn.transaction():
                # 1. Upsert master document
                doc_row = await conn.fetchrow(
                    """
                    INSERT INTO documents (document_id, title, source_path, file_hash, file_type, allowed_roles, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6::jsonb, CURRENT_TIMESTAMP)
                    ON CONFLICT (document_id) DO UPDATE
                    SET title = EXCLUDED.title,
                        source_path = EXCLUDED.source_path,
                        file_hash = EXCLUDED.file_hash,
                        file_type = EXCLUDED.file_type,
                        allowed_roles = EXCLUDED.allowed_roles,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING id
                    """,
                    document_id, title, source_path, file_hash, file_type, roles_json
                )
                doc_uuid = doc_row["id"]

                # 2. Insert/replace chunks with 16-bit halfvec quantization
                await conn.execute("DELETE FROM document_chunks WHERE document_id = $1", doc_uuid)
                for idx, chunk in enumerate(chunks):
                    chunk_id = chunk.get("chunk_id", f"{document_id}_chunk_{idx+1}")
                    content = chunk.get("content", "")
                    embedding = chunk.get("embedding", [])
                    vector_str = cls.format_halfvec(embedding)
                    model = chunk.get("embedding_model", "text-embedding-3-large")
                    tokens = chunk.get("token_count", len(content.split()))

                    await conn.execute(
                        """
                        INSERT INTO document_chunks (document_id, chunk_id, chunk_index, content, token_count, embedding, embedding_model)
                        VALUES ($1, $2, $3, $4, $5, $6::vector::halfvec(1536)::vector, $7)
                        ON CONFLICT (chunk_id) DO UPDATE
                        SET content = EXCLUDED.content,
                            token_count = EXCLUDED.token_count,
                            embedding = EXCLUDED.embedding,
                            embedding_model = EXCLUDED.embedding_model
                        """,
                        doc_uuid, chunk_id, idx, content, tokens, vector_str, model
                    )

                return str(doc_uuid)

    @classmethod
    async def get_document_by_hash(cls, file_hash: str) -> Optional[dict]:
        """Lookup document existence by SHA-256 hash using idx_documents_file_hash index."""
        pool = await cls.get_pool()
        async with pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    "SELECT id, document_id, title, file_hash, created_at FROM documents WHERE file_hash = $1",
                    file_hash
                )
                return dict(row) if row else None
            except Exception:
                return None

    @classmethod
    async def delete_document(cls, document_id: str) -> bool:
        """Delete document from documents table (cascading to all document_chunks)."""
        pool = await cls.get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute("DELETE FROM documents WHERE document_id = $1", document_id)
            return "DELETE 1" in result

    @classmethod
    async def list_documents(
        cls,
        user_roles: Optional[List[str]] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[dict]:
        """
        List documents pre-filtered by user_roles using the GIN index on allowed_roles.
        Fails closed: if user_roles is empty or None, returns [] without querying the DB.
        """
        if not user_roles:
            return []

        clean_roles = [r for r in user_roles if isinstance(r, str) and re.match(r"^[a-zA-Z0-9_\-\.\@]+$", r)]
        if not clean_roles:
            return []

        pool = await cls.get_pool()
        async with pool.acquire() as conn:
            query = """
                SELECT d.id, d.document_id, d.title, d.file_hash, d.allowed_roles, d.created_at,
                       COUNT(c.id) AS chunk_count
                FROM documents d
                LEFT JOIN document_chunks c ON d.id = c.document_id
                WHERE d.allowed_roles ?| $1::text[]
                GROUP BY d.id, d.document_id, d.title, d.file_hash, d.allowed_roles, d.created_at
                ORDER BY d.created_at DESC
                LIMIT $2 OFFSET $3;
            """
            rows = await conn.fetch(query, clean_roles, limit, offset)
            return [
                {
                    "id": str(r["id"]),
                    "document_id": r["document_id"],
                    "title": r["title"],
                    "file_hash": r["file_hash"],
                    "allowed_roles": json.loads(r["allowed_roles"]) if isinstance(r["allowed_roles"], str) else (r["allowed_roles"] or []),
                    "chunk_count": int(r["chunk_count"]),
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in rows
            ]

    # -----------------------------------------------------------------------
    # LangGraph PostgreSQL Checkpoint Persistence (sdlc_workflow_checkpoints)
    # -----------------------------------------------------------------------

    @classmethod
    async def save_workflow_checkpoint(
        cls,
        thread_id: str,
        checkpoint_id: str,
        checkpoint_payload: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
        checkpoint_ns: str = "",
        parent_checkpoint_id: Optional[str] = None,
    ) -> bool:
        """
        Persist a LangGraph SDLC workflow state checkpoint into `sdlc_workflow_checkpoints`
        so multi-worker instances can resume crashed or human-gated (HITL) workflows.
        """
        pool = await cls.get_pool()
        payload_json = json.dumps(checkpoint_payload, default=str)
        meta_json = json.dumps(metadata or {}, default=str)
        sql = """
            INSERT INTO sdlc_workflow_checkpoints (
                thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, checkpoint_payload, metadata
            )
            VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb)
            ON CONFLICT (thread_id, checkpoint_ns, checkpoint_id) DO UPDATE
            SET checkpoint_payload = EXCLUDED.checkpoint_payload,
                metadata = EXCLUDED.metadata,
                created_at = CURRENT_TIMESTAMP
        """
        async with pool.acquire() as conn:
            res = await conn.execute(
                sql,
                thread_id,
                checkpoint_ns,
                checkpoint_id,
                parent_checkpoint_id,
                payload_json,
                meta_json,
            )
            return "INSERT" in str(res) or "UPDATE" in str(res)

    @classmethod
    async def load_workflow_checkpoint(
        cls,
        thread_id: str,
        checkpoint_ns: str = "",
        checkpoint_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Load the latest (or specific `checkpoint_id`) LangGraph workflow state checkpoint
        from `sdlc_workflow_checkpoints` for crash-resilient multi-worker resumption.
        """
        pool = await cls.get_pool()
        async with pool.acquire() as conn:
            if checkpoint_id:
                row = await conn.fetchrow(
                    """
                    SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, checkpoint_payload, metadata
                    FROM sdlc_workflow_checkpoints
                    WHERE thread_id = $1 AND checkpoint_ns = $2 AND checkpoint_id = $3
                    LIMIT 1
                    """,
                    thread_id,
                    checkpoint_ns,
                    checkpoint_id,
                )
            else:
                row = await conn.fetchrow(
                    """
                    SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, checkpoint_payload, metadata
                    FROM sdlc_workflow_checkpoints
                    WHERE thread_id = $1 AND checkpoint_ns = $2
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    thread_id,
                    checkpoint_ns,
                )
            if not row:
                return None
            record = dict(row)
            for field in ("checkpoint_payload", "metadata"):
                if isinstance(record.get(field), str):
                    try:
                        record[field] = json.loads(record[field])
                    except Exception:
                        pass
            return record

    @classmethod
    async def list_workflow_checkpoints(
        cls,
        thread_id: str,
        checkpoint_ns: str = "",
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        List chronological LangGraph workflow state checkpoints from `sdlc_workflow_checkpoints`
        for time-travel inspection and audit traceability.
        """
        pool = await cls.get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, checkpoint_payload, metadata, created_at
                FROM sdlc_workflow_checkpoints
                WHERE thread_id = $1 AND checkpoint_ns = $2
                ORDER BY created_at ASC
                LIMIT $3
                """,
                thread_id,
                checkpoint_ns,
                limit,
            )
            results: List[Dict[str, Any]] = []
            for row in rows:
                record = dict(row)
                for field in ("checkpoint_payload", "metadata"):
                    if isinstance(record.get(field), str):
                        try:
                            record[field] = json.loads(record[field])
                        except Exception:
                            pass
                results.append(record)
            return results

    # -----------------------------------------------------------------------
    # Transactional Outbox & Distributed Worker Queue (FOR UPDATE SKIP LOCKED)
    # -----------------------------------------------------------------------

    @classmethod
    async def enqueue_outbox_event(
        cls,
        event_key: str,
        aggregate_type: str,
        payload: Dict[str, Any],
    ) -> Optional[str]:
        """
        Idempotently persist an event into sdlc_outbox_events within an atomic transaction.
        Returns the event UUID string if newly inserted or existing.
        """
        pool = await cls.get_pool()
        payload_json = json.dumps(payload)
        async with pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    INSERT INTO sdlc_outbox_events (event_key, aggregate_type, payload, status)
                    VALUES ($1, $2, $3::jsonb, 'PENDING')
                    ON CONFLICT (event_key) DO NOTHING
                    RETURNING id
                    """,
                    event_key,
                    aggregate_type,
                    payload_json,
                )
                return str(row["id"]) if row else None

    @classmethod
    async def claim_next_outbox_batch(
        cls,
        worker_id: str,
        batch_size: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Claim a batch of PENDING outbox tasks using PostgreSQL row-level locking
        (`FOR UPDATE SKIP LOCKED`) so concurrent agent workers never collide or block.
        """
        pool = await cls.get_pool()
        sql = """
            WITH claimed AS (
                SELECT id
                FROM sdlc_outbox_events
                WHERE status = 'PENDING'
                ORDER BY created_at ASC
                LIMIT $2
                FOR UPDATE SKIP LOCKED
            )
            UPDATE sdlc_outbox_events e
            SET status = 'PROCESSING',
                locked_by = $1,
                locked_at = CURRENT_TIMESTAMP,
                attempts = e.attempts + 1
            FROM claimed
            WHERE e.id = claimed.id
            RETURNING e.id, e.event_key, e.aggregate_type, e.payload, e.status, e.locked_by, e.attempts
        """
        async with pool.acquire() as conn:
            async with conn.transaction():
                rows = await conn.fetch(sql, worker_id, batch_size)
                results: List[Dict[str, Any]] = []
                for r in rows:
                    item = dict(r)
                    if isinstance(item.get("payload"), str):
                        try:
                            item["payload"] = json.loads(item["payload"])
                        except Exception:
                            pass
                    results.append(item)
                return results

    @classmethod
    async def complete_outbox_event(
        cls,
        event_id: str,
        status: str = "COMPLETED",
    ) -> bool:
        """Mark a claimed outbox event as COMPLETED or FAILED."""
        pool = await cls.get_pool()
        sql = """
            UPDATE sdlc_outbox_events
            SET status = $2,
                processed_at = CURRENT_TIMESTAMP
            WHERE id = $1::uuid
        """
        async with pool.acquire() as conn:
            res = await conn.execute(sql, event_id, status)
            return "UPDATE 1" in res

    # =========================================================================
    # Token Consumption Ledger & Managed Budget Limit Controls
    # =========================================================================

    @classmethod
    async def record_token_consumption(
        cls,
        caller_id: str,
        prompt_tokens: int,
        completion_tokens: int,
        model: str = "gpt-4o",
        operation_type: str = "rag_query",
        metadata: Optional[Dict[str, Any]] = None,
        default_budget_limit: int = 50000,
    ) -> Dict[str, Any]:
        """
        Persist token consumption event to token_consumption_ledger and atomically
        accumulate usage in token_managed_limits. If enforce_limit is enabled and
        cumulative tokens reach or exceed max_budget_tokens, is_blocked is set to TRUE.
        """
        pool = await cls.get_pool()
        cid = (caller_id or "anonymous").strip() or "anonymous"
        p_tokens = max(0, int(prompt_tokens))
        c_tokens = max(0, int(completion_tokens))
        t_tokens = p_tokens + c_tokens
        meta_json = json.dumps(metadata or {})

        async with pool.acquire() as conn:
            async with conn.transaction():
                ledger_row = await conn.fetchrow(
                    """
                    INSERT INTO token_consumption_ledger (
                        caller_id, model, prompt_tokens, completion_tokens, total_tokens, operation_type, metadata
                    )
                    VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                    RETURNING id::text, caller_id, total_tokens, created_at
                    """,
                    cid,
                    model,
                    p_tokens,
                    c_tokens,
                    t_tokens,
                    operation_type,
                    meta_json,
                )

                limit_row = await conn.fetchrow(
                    """
                    INSERT INTO token_managed_limits (
                        caller_id, max_budget_tokens, current_tokens, enforce_limit, is_blocked, updated_at
                    )
                    VALUES ($1, $2, $3, TRUE, FALSE, CURRENT_TIMESTAMP)
                    ON CONFLICT (caller_id) DO UPDATE
                    SET current_tokens = token_managed_limits.current_tokens + EXCLUDED.current_tokens,
                        is_blocked = CASE
                            WHEN token_managed_limits.enforce_limit
                                 AND (token_managed_limits.current_tokens + EXCLUDED.current_tokens >= token_managed_limits.max_budget_tokens)
                            THEN TRUE
                            ELSE token_managed_limits.is_blocked
                        END,
                        updated_at = CURRENT_TIMESTAMP
                    RETURNING caller_id, max_budget_tokens, current_tokens, enforce_limit, is_blocked
                    """,
                    cid,
                    int(default_budget_limit),
                    t_tokens,
                )

                return {
                    "ledger_id": str(ledger_row["id"]) if ledger_row else None,
                    "caller_id": limit_row["caller_id"],
                    "total_tokens_consumed": t_tokens,
                    "cumulative_tokens": int(limit_row["current_tokens"]),
                    "max_budget_tokens": int(limit_row["max_budget_tokens"]),
                    "enforce_limit": bool(limit_row["enforce_limit"]),
                    "is_blocked": bool(limit_row["is_blocked"]),
                }

    @classmethod
    async def check_token_limit(
        cls,
        caller_id: str,
        requested_tokens: int = 0,
        default_budget_limit: int = 50000,
    ) -> Tuple[bool, int, int, bool, Optional[str]]:
        """
        Evaluate caller quota against token_managed_limits.
        Returns:
            (allowed, current_tokens, max_budget_tokens, enforce_limit, reason)
        """
        pool = await cls.get_pool()
        cid = (caller_id or "anonymous").strip() or "anonymous"
        req = max(0, int(requested_tokens))

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT caller_id, max_budget_tokens, current_tokens, enforce_limit, is_blocked
                FROM token_managed_limits
                WHERE caller_id = $1
                """,
                cid,
            )

            if not row:
                row = await conn.fetchrow(
                    """
                    SELECT caller_id, max_budget_tokens, current_tokens, enforce_limit, is_blocked
                    FROM token_managed_limits
                    WHERE caller_id = 'global'
                    """
                )

            if row:
                current_tokens = int(row["current_tokens"])
                max_budget = int(row["max_budget_tokens"])
                enforce = bool(row["enforce_limit"])
                is_blocked = bool(row["is_blocked"])
            else:
                current_tokens = 0
                max_budget = int(default_budget_limit)
                enforce = True
                is_blocked = False

            if is_blocked:
                return (
                    False,
                    current_tokens,
                    max_budget,
                    enforce,
                    f"Token consumption turned off for caller '{cid}': account is blocked or reached managed limit.",
                )

            if enforce and (current_tokens + req > max_budget):
                return (
                    False,
                    current_tokens,
                    max_budget,
                    enforce,
                    f"Token managed limit reached: projected tokens ({current_tokens + req}) exceed managed limit ({max_budget}). Token consumption turned off.",
                )

            return True, current_tokens, max_budget, enforce, None

    @classmethod
    async def get_token_managed_limits(
        cls,
        caller_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Fetch managed limit configurations and current consumption."""
        pool = await cls.get_pool()
        async with pool.acquire() as conn:
            if caller_id:
                rows = await conn.fetch(
                    """
                    SELECT caller_id, max_budget_tokens, current_tokens, enforce_limit, is_blocked,
                           tier, reset_interval, last_reset_at, created_at, updated_at
                    FROM token_managed_limits
                    WHERE caller_id = $1
                    """,
                    caller_id.strip(),
                )
                if not rows:
                    rows = await conn.fetch(
                        """
                        SELECT caller_id, max_budget_tokens, current_tokens, enforce_limit, is_blocked,
                               tier, reset_interval, last_reset_at, created_at, updated_at
                        FROM token_managed_limits
                        WHERE caller_id = 'global'
                        """
                    )
            else:
                rows = await conn.fetch(
                    """
                    SELECT caller_id, max_budget_tokens, current_tokens, enforce_limit, is_blocked,
                           tier, reset_interval, last_reset_at, created_at, updated_at
                    FROM token_managed_limits
                    ORDER BY caller_id ASC
                    """
                )
            return [dict(r) for r in rows]

    @classmethod
    async def set_token_managed_limit(
        cls,
        caller_id: str,
        max_budget_tokens: Optional[int] = None,
        enforce_limit: Optional[bool] = None,
        is_blocked: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """
        Update or create a managed token limit and controls (toggle enforce_limit or is_blocked kill-switch).
        """
        pool = await cls.get_pool()
        cid = (caller_id or "anonymous").strip() or "anonymous"

        async with pool.acquire() as conn:
            existing = await conn.fetchrow(
                "SELECT caller_id, max_budget_tokens, current_tokens, enforce_limit, is_blocked FROM token_managed_limits WHERE caller_id = $1",
                cid,
            )
            cur_limit = int(existing["max_budget_tokens"]) if existing else 50000
            cur_enforce = bool(existing["enforce_limit"]) if existing else True
            cur_blocked = bool(existing["is_blocked"]) if existing else False
            cur_tokens = int(existing["current_tokens"]) if existing else 0

            new_limit = cur_limit if max_budget_tokens is None else int(max_budget_tokens)
            new_enforce = cur_enforce if enforce_limit is None else bool(enforce_limit)
            new_blocked = cur_blocked if is_blocked is None else bool(is_blocked)

            if is_blocked is None:
                if not new_enforce:
                    new_blocked = False
                elif cur_tokens < new_limit:
                    new_blocked = False

            row = await conn.fetchrow(
                """
                INSERT INTO token_managed_limits (
                    caller_id, max_budget_tokens, current_tokens, enforce_limit, is_blocked, updated_at
                )
                VALUES ($1, $2, $3, $4, $5, CURRENT_TIMESTAMP)
                ON CONFLICT (caller_id) DO UPDATE
                SET max_budget_tokens = EXCLUDED.max_budget_tokens,
                    enforce_limit = EXCLUDED.enforce_limit,
                    is_blocked = EXCLUDED.is_blocked,
                    updated_at = CURRENT_TIMESTAMP
                RETURNING caller_id, max_budget_tokens, current_tokens, enforce_limit, is_blocked
                """,
                cid,
                new_limit,
                cur_tokens,
                new_enforce,
                new_blocked,
            )
            return dict(row)

    @classmethod
    async def reset_token_usage(cls, caller_id: str) -> bool:
        """Reset current token counter and clear is_blocked for a caller."""
        pool = await cls.get_pool()
        cid = (caller_id or "anonymous").strip() or "anonymous"
        async with pool.acquire() as conn:
            res = await conn.execute(
                """
                UPDATE token_managed_limits
                SET current_tokens = 0,
                    is_blocked = FALSE,
                    last_reset_at = CURRENT_TIMESTAMP,
                    updated_at = CURRENT_TIMESTAMP
                WHERE caller_id = $1
                """,
                cid,
            )
            return "UPDATE 1" in res

    @classmethod
    async def get_token_usage_ledger(
        cls,
        caller_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Retrieve recent individual token consumption events."""
        pool = await cls.get_pool()
        fetch_limit = max(1, min(1000, int(limit)))
        async with pool.acquire() as conn:
            if caller_id:
                rows = await conn.fetch(
                    """
                    SELECT id::text, caller_id, model, prompt_tokens, completion_tokens,
                           total_tokens, operation_type, metadata, created_at
                    FROM token_consumption_ledger
                    WHERE caller_id = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                    """,
                    caller_id.strip(),
                    fetch_limit,
                )
            else:
                rows = await conn.fetch(
                    """
                    SELECT id::text, caller_id, model, prompt_tokens, completion_tokens,
                           total_tokens, operation_type, metadata, created_at
                    FROM token_consumption_ledger
                    ORDER BY created_at DESC
                    LIMIT $1
                    """,
                    fetch_limit,
                )
            return [dict(r) for r in rows]
