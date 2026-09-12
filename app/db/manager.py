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
    async def secure_search(cls, query_vector: List[float], user_roles: List[str], limit: int = 3):
        pool = await cls.get_pool()
        vector_str = f"[{','.join(map(str, query_vector))}]"
        
        sql = """
            SELECT document_id, title, content, allowed_roles, 
                   1 - (embedding <=> $1::vector) as similarity
            FROM enterprise_documents
            WHERE allowed_roles ?| $2::text[]
              AND (embedding_model = 'text-embedding-3-large' OR embedding_model IS NULL)
            ORDER BY embedding <=> $1::vector
            LIMIT $3
        """
        async with pool.acquire() as conn:
            return await conn.fetch(sql, vector_str, user_roles, limit)

    @classmethod
    async def ingest_document(cls, document_id: str, title: str, content: str, allowed_roles: List[str], embedding: List[float]):
        pool = await cls.get_pool()
        vector_str = f"[{','.join(map(str, embedding))}]"
        roles_json = json.dumps(allowed_roles)
        
        sql = """
            INSERT INTO enterprise_documents (document_id, title, content, allowed_roles, embedding)
            VALUES ($1, $2, $3, $4::jsonb, $5::vector)
            ON CONFLICT (document_id) DO UPDATE 
            SET title = EXCLUDED.title, content = EXCLUDED.content, 
                allowed_roles = EXCLUDED.allowed_roles, embedding = EXCLUDED.embedding
        """
        async with pool.acquire() as conn:
            await conn.execute(sql, document_id, title, content, roles_json, vector_str)
