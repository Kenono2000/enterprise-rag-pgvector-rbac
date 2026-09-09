from app.db.manager import DatabaseManager
from app.db.llm import generate_embedding

async def get_architectural_context(ticket_description: str, user_roles: list[str]) -> list[str]:
    """
    Evaluates role access DURING vector graph traversal using the ?| operator.
    Restricts the agent to only reading Architecture Decision Records (ADRs) 
    and patterns that the ticket submitter is cryptographically cleared to see.
    """
    # 1. Generate embedding (Matryoshka representation 1536d)
    embedding_1536 = await generate_embedding(ticket_description, dimensions=1536)
    
    # 2. Lease asyncpg connection, query index, release immediately before agent loop
    # We reuse the logic from DatabaseManager which handles the ?| operator and distance sort
    pool = await DatabaseManager.get_pool()
    
    query = """
    SELECT content, embedding <=> $1::vector AS distance
    FROM enterprise_documents
    WHERE allowed_roles ?| $2::text[]
    ORDER BY distance ASC
    LIMIT 4;
    """
    
    vector_str = f"[{','.join(map(str, embedding_1536))}]"
    
    async with pool.acquire() as conn:
        records = await conn.fetch(query, vector_str, user_roles)
        
    return [r["content"] for r in records]
