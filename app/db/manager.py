import os
import asyncpg
import json
from typing import Optional, List
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv(), override=True)

DATABASE_URL = os.getenv("DATABASE_URL")

class DatabaseManager:
    _pool: Optional[asyncpg.Pool] = None

    @classmethod
    async def get_pool(cls) -> asyncpg.Pool:
        if cls._pool is None:
            if not DATABASE_URL:
                raise ValueError("❌ DATABASE_URL is not set")
            cls._pool = await asyncpg.create_pool(
                DATABASE_URL, 
                min_size=2, 
                max_size=10
            )
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
