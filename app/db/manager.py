import os
import asyncio
import asyncpg
import json
from typing import Optional, List
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
    async def secure_search(cls, query_vector: List[float], user_roles: List[str], limit: int = 10):
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
        vector_str = f"[{','.join(map(str, query_vector))}]"
        
        sql = """
            SELECT d.document_id, d.title, c.content, d.allowed_roles, 
                   1 - (c.embedding <=> $1::vector) as similarity
            FROM document_chunks c
            JOIN documents d ON c.document_id = d.id
            WHERE d.allowed_roles ?| $2::text[]
              AND (c.embedding_model = 'text-embedding-3-large' OR c.embedding_model IS NULL)
            ORDER BY c.embedding <=> $1::vector
            LIMIT $3
        """
        async with pool.acquire() as conn:
            return await conn.fetch(sql, vector_str, sanitized_roles, limit)


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
        Ingest a document and its chunks into normalized documents and document_chunks tables.
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

                # 2. Insert/replace chunks
                await conn.execute("DELETE FROM document_chunks WHERE document_id = $1", doc_uuid)
                for idx, chunk in enumerate(chunks):
                    chunk_id = chunk.get("chunk_id", f"{document_id}_chunk_{idx+1}")
                    content = chunk.get("content", "")
                    embedding = chunk.get("embedding", [])
                    vector_str = f"[{','.join(map(str, embedding))}]"
                    model = chunk.get("embedding_model", "text-embedding-3-large")
                    tokens = chunk.get("token_count", len(content.split()))

                    await conn.execute(
                        """
                        INSERT INTO document_chunks (document_id, chunk_id, chunk_index, content, token_count, embedding, embedding_model)
                        VALUES ($1, $2, $3, $4, $5, $6::vector, $7)
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

