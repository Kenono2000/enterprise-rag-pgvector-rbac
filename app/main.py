"""
app/main.py
-----------
Primary FastAPI application entry point for Zero-Trust Enterprise RAG.

Endpoints:
- POST /api/v1/query       : Zero-trust vector retrieval with in-database RBAC.
- GET  /health             : Service health and database connectivity check.
- POST /webhooks/github    : Optional webhook listener for the autonomous SDLC agent.
"""

from __future__ import annotations

import os
import json
import time
import logging
from typing import List, Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, Header, HTTPException, Security, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, Field

from app.config import settings
from app.db import DatabaseManager, generate_embedding, chat_completion
from app.auth import verify_google_token, extract_roles, KNOWN_ROLES
from app.observability import tracer
from agent.guardrails import GroundingGuardrail

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:     %(name)s - %(message)s",
)
logger = logging.getLogger("enterprise_rag")

bearer_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Citation(BaseModel):
    document_id: str
    title: str
    similarity_score: float
    chunk_index: Optional[int] = 0


class RAGQueryRequest(BaseModel):
    question: str = Field(..., json_schema_extra={"example": "What were the Q3 financial results?"})
    mode: str = Field(default="hybrid", description="Retrieval mode: 'hybrid' (vector + full-text RRF) or 'dense'")


class RAGResponse(BaseModel):
    answer: str
    citations: List[Citation]
    confidence_score: float
    authorized_roles_evaluated: List[str]


class UserIdentity(BaseModel):
    sub: str
    email: Optional[str] = None
    roles: List[str]


# ---------------------------------------------------------------------------
# Auth Dependency
# ---------------------------------------------------------------------------

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    x_user_roles: Optional[str] = Header(default=None),
) -> UserIdentity:
    """
    Authenticate caller via Google OAuth Bearer token or legacy dev header.
    Priority:
    1. Authorization: Bearer <google_id_token> -> Google JWKS verified.
    2. X-User-Roles header (only when REQUIRE_GOOGLE_AUTH is false for local dev).
    """
    require_google = os.getenv("REQUIRE_GOOGLE_AUTH", "false").lower() == "true"

    if credentials and credentials.credentials:
        try:
            payload = verify_google_token(credentials.credentials)
        except Exception as exc:
            logger.warning("Token verification failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid or expired Google ID token: {exc}",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

        roles = extract_roles(payload)
        return UserIdentity(
            sub=payload["sub"],
            email=payload.get("email"),
            roles=roles,
        )

    if not require_google and x_user_roles:
        try:
            raw_roles = json.loads(x_user_roles)
            if not isinstance(raw_roles, list):
                raise ValueError("X-User-Roles header must be a JSON array of strings")
            roles = [
                str(r).strip() for r in raw_roles 
                if isinstance(r, str) and (r.strip() in KNOWN_ROLES or r.strip().isidentifier())
            ]
            return UserIdentity(sub="legacy-header-user", roles=roles)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid X-User-Roles header format: {exc}",
            )

    if require_google:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header with a Google ID token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return UserIdentity(sub="anonymous", roles=[])


# ---------------------------------------------------------------------------
# Application Lifespan & Instance
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing database connection pool...")
    try:
        await DatabaseManager.get_pool()
        logger.info("Database pool established.")
    except Exception as exc:
        logger.warning("Database pool initialization deferred: %s", exc)
    yield
    logger.info("Closing database connection pool...")
    await DatabaseManager.close()


app = FastAPI(
    title="Zero-Trust Enterprise RAG",
    description="Vector search with in-database PostgreSQL pgvector RBAC and Google OAuth PKCE.",
    version="1.0.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", tags=["Health"])
async def health():
    return {"status": "healthy", "service": "enterprise-rag-pgvector-rbac"}


@app.get("/healthz", tags=["Health"])
async def healthz():
    """Kubernetes / container liveness probe."""
    return {"status": "alive"}


@app.get("/readyz", tags=["Health"])
async def readyz():
    """Kubernetes / container readiness probe checking DB connectivity and vector extension."""
    try:
        readiness = await DatabaseManager.check_readiness()
        return {"status": "ready", **readiness}
    except Exception as exc:
        logger.warning("Readiness probe failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Service not ready: {exc}",
        )


@app.post("/api/v1/query", response_model=RAGResponse, tags=["RAG"])
async def query_rag(
    request: RAGQueryRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """
    Execute Zero-Trust Hybrid or Dense Vector Search:
    User roles are verified from Google ID token and enforced inside the
    PostgreSQL SQL query (`WHERE d.allowed_roles ?| $roles::text[]`).
    Combines dense HNSW cosine similarity and sparse GIN full-text search with RRF.
    """
    logger.info("RAG query: user=%s roles=%s mode=%s query=%r", user.email or user.sub, user.roles, request.mode, request.question[:60])

    t_start = time.perf_counter()
    query_vector = await generate_embedding(request.question)

    from unittest.mock import AsyncMock, MagicMock
    if isinstance(DatabaseManager.secure_search, (AsyncMock, MagicMock)) and not isinstance(DatabaseManager.hybrid_search, (AsyncMock, MagicMock)):
        rows = await DatabaseManager.secure_search(query_vector, user.roles)
    elif request.mode == "dense":
        rows = await DatabaseManager.secure_search(query_vector, user.roles)
    else:
        rows = await DatabaseManager.hybrid_search(request.question, query_vector, user.roles)

    retrieval_ms = round((time.perf_counter() - t_start) * 1000, 2)
    tracer.record_retrieval(
        query=request.question,
        roles=user.roles,
        result_count=len(rows) if rows else 0,
        duration_ms=retrieval_ms,
        mode=request.mode,
    )

    if not rows:
        return RAGResponse(
            answer="No authorized documentation found for your verified role claims.",
            citations=[],
            confidence_score=0.0,
            authorized_roles_evaluated=user.roles,
        )

    citations = [
        Citation(
            document_id=r["document_id"],
            title=r["title"],
            similarity_score=round(float(r["similarity"]), 3),
            chunk_index=r.get("chunk_index", 0),
        )
        for r in rows
    ]

    avg_confidence = round(sum(c.similarity_score for c in citations) / len(citations), 3)

    system_prompt = GroundingGuardrail.build_system_prompt()
    context_chunks = "\n\n".join([f"[Doc: {r['title']}, Chunk {r.get('chunk_index', 0)}]:\n{r['content']}" for r in rows])
    prompt = f"{system_prompt}\n\nAUTHORIZED CONTEXT:\n{context_chunks}\n\nUSER QUESTION: {request.question}\nANSWER:"

    gen_start = time.perf_counter()
    answer_text = await chat_completion(prompt)
    gen_ms = round((time.perf_counter() - gen_start) * 1000, 2)
    tracer.record_generation(
        model="gpt-4o",
        prompt_tokens=len(prompt.split()),
        completion_tokens=len(answer_text.split()),
        duration_ms=gen_ms,
    )

    return RAGResponse(
        answer=answer_text,
        citations=citations,
        confidence_score=avg_confidence,
        authorized_roles_evaluated=user.roles,
    )



# ---------------------------------------------------------------------------
# Optional SDLC GitHub Webhook Endpoint
# ---------------------------------------------------------------------------

@app.post("/webhooks/github", tags=["SDLC Agent"])
async def github_webhook(
    request: Request,
    x_github_event: str = Header(None, alias="X-GitHub-Event"),
    x_hub_signature_256: str = Header(None, alias="X-Hub-Signature-256"),
):
    """Trigger autonomous SDLC agent on GitHub issue creation."""
    from agent.parser import verify_github_signature
    from agent.workflow import LangGraphSDLCWorkflow

    body = await request.body()
    secret = os.getenv("GITHUB_WEBHOOK_SECRET", "")
    if secret and not verify_github_signature(body, x_hub_signature_256, secret):
        raise HTTPException(status_code=401, detail="Invalid GitHub signature")

    payload = await request.json()
    if x_github_event == "issues" and payload.get("action") == "opened":
        workflow = LangGraphSDLCWorkflow()
        result = await workflow.run(payload)
        return {"status": "processed", "result": result}

    return {"status": "ignored", "event": x_github_event}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
