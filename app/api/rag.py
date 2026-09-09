from fastapi import APIRouter, Depends, HTTPException, Header, status
from pydantic import BaseModel, Field
from typing import List, Optional
import json
from app.db.manager import DatabaseManager
from app.db.llm import generate_embedding, chat_completion

router = APIRouter(prefix="/api/v1")

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

async def get_current_user_roles(
    x_user_roles: Optional[str] = Header(
        default='["finance_executive"]', 
        description="Simulated Auth0 JWT role claims array"
    )
) -> List[str]:
    try:
        roles = json.loads(x_user_roles)
        return roles
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid JWT roles")

@router.post("/query", response_model=RAGResponse)
async def query_rag(
    request: RAGQueryRequest,
    user_roles: List[str] = Depends(get_current_user_roles)
):
    query_vector = await generate_embedding(request.question)
    rows = await DatabaseManager.secure_search(query_vector, user_roles)
    
    if not rows:
        return RAGResponse(
            answer="No authorized documentation found.",
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
    context_chunks = "\n\n".join([f"[{r['title']}]: {r['content']}" for r in rows])
    
    prompt = f"Answer strictly using context:\n\n{context_chunks}\n\nQuestion: {request.question}"
    answer_text = await chat_completion(prompt)
        
    return RAGResponse(
        answer=answer_text,
        citations=citations,
        confidence_score=avg_confidence,
        authorized_roles_evaluated=user_roles
    )
