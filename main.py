import os
import json
import asyncpg
from typing import List, Optional
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, HTTPException, Header, status
from pydantic import BaseModel, Field
from openai import AsyncOpenAI
DATABASE_URL = os.getenv(
    "DATABASE_URL", 
    "postgresql://rag_user:rag_password@localhost:5432/enterprise_rag"
)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "mock-key-for-local-demo")
class Citation(BaseModel):
    document_id: str
    title: str
    similarity_score: float
class RAGQueryRequest(BaseModel):
    question: str = Field(..., example="What were the Q3 financial results?")
class RAGResponse(BaseModel):
    answer: str
    citations: List[Citation]
    confidence_score: float
    authorized_roles_evaluated: List[str]
class IngestDocumentRequest(BaseModel):
    document_id: str
    title: str
    content: str
    allowed_roles: List[str]
db_pool: Optional[asyncpg.Pool] = None
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY != "mock-key-for-local-demo" else None
@asynccontextmanager
async def lifespan(app: FastAPI):
    global db_pool
    db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    yield
    await db_pool.close()
app = FastAPI(
    title="Zero-Trust Enterprise RAG Microservice",
    description="Asynchronous RAG API with In-Database RBAC and Matryoshka Vector Indexing",
    version="2.0.0",
    lifespan=lifespan
)
async def get_current_user_roles(
    x_user_roles: Optional[str] = Header(
        default='["finance_executive"]', 
        description="Simulated Auth0 JWT role claims array"
    )
) -> List[str]:
    try:
        roles = json.loads(x_user_roles)
        if not isinstance(roles, list):
            raise ValueError()
        return roles
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid JWT roles claim structure"
        )
async def generate_matryoshka_embedding(text: str) -> List[float]:
    if openai_client:
        response = await openai_client.embeddings.create(
            model="text-embedding-3-large",
            input=text,
            dimensions=1536 
        )
        return response.data[0].embedding
    else:
        return [0.01 * (i % 5) for i in range(1536)]
@app.get("/health", tags=["Health"])
async def health_check():
    return {"status": "healthy", "service": "Zero-Trust RAG Microservice"}
@app.post("/api/v1/query", response_model=RAGResponse, tags=["RAG Retrieval"])
async def query_rag(
    request: RAGQueryRequest,
    user_roles: List[str] = Depends(get_current_user_roles)
):
    query_vector = await generate_matryoshka_embedding(request.question)
    vector_str = f"[{','.join(map(str, query_vector))}]"
    roles_json = json.dumps(user_roles)
    helper_sql = 
    async with db_pool.acquire() as conn:
        rows = await conn.fetch(helper_sql, vector_str, roles_json)
    if not rows:
        return RAGResponse(
            answer="No authorized documentation found matching your security credentials.",
            citations=[],
            confidence_score=0.0,
            authorized_roles_evaluated=user_roles
        )
    citations = [
        Citation(
            document_id=r["document_id"],
            title=r["title"],
            similarity_score=round(float(r["similarity"]), 3)
        )
        for r in rows
    ]
    avg_confidence = round(sum(c.similarity_score for c in citations) / len(citations), 3)
    context_chunks = "\n
    if openai_client:
        prompt = f"Answer the user's question strictly using the provided context:\n\n{context_chunks}\n\nQuestion: {request.question}"
        completion = await openai_client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0
        )
        answer_text = completion.choices[0].message.content
    else:
        answer_text = f"[Local Demo Grounded Response]: Operating margins in Q3 increased by 14.2% based on authorized document '{rows[0]['title']}'."
    return RAGResponse(
        answer=answer_text,
        citations=citations,
        confidence_score=avg_confidence,
        authorized_roles_evaluated=user_roles
    )
@app.post("/api/v1/ingest", tags=["Ingestion"])
async def ingest_document(
    doc: IngestDocumentRequest,
    user_roles: List[str] = Depends(get_current_user_roles)
):
    embedding = await generate_matryoshka_embedding(doc.content)
    vector_str = f"[{','.join(map(str, embedding))}]"
    roles_json = json.dumps(doc.allowed_roles)
    insert_sql = 
    async with db_pool.acquire() as conn:
        await conn.execute(insert_sql, doc.document_id, doc.title, doc.content, roles_json, vector_str)
    return {"status": "success", "document_id": doc.document_id, "roles_assigned": doc.allowed_roles}
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)