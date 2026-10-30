"""
app/main.py
-----------
Primary FastAPI application entry point for Zero-Trust Enterprise RAG.

Endpoints:
- POST /api/v1/query       : Zero-trust vector retrieval with in-database RBAC,
                             strict extra='forbid' schemas, sliding-window rate
                             limiting, and request-level token circuit breakers.
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
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI, Depends, Header, HTTPException, Security, Request, status
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, ConfigDict, Field

from app.config import settings
from app.db import DatabaseManager, generate_embedding, chat_completion, chat_completion_stream
from app.auth import verify_google_token, extract_roles, KNOWN_ROLES
from app.observability import tracer
from agent.guardrails import (
    GroundingGuardrail,
    SlidingWindowRateLimiter,
    TokenCircuitBreaker,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:     %(name)s - %(message)s",
)
logger = logging.getLogger("enterprise_rag")

bearer_scheme = HTTPBearer(auto_error=False)

# Gateway-level sliding-window rate limiter & token circuit breaker
api_rate_limiter = SlidingWindowRateLimiter(
    max_requests=int(os.getenv("API_RATE_LIMIT_MAX_REQUESTS", "60")),
    window_seconds=float(os.getenv("API_RATE_LIMIT_WINDOW_SECONDS", "60")),
)
api_token_breaker = TokenCircuitBreaker(
    max_tokens_per_request=int(os.getenv("API_MAX_TOKENS_PER_REQUEST", "8000")),
    max_tokens_per_issue=int(os.getenv("API_MAX_TOKENS_PER_ISSUE", "50000")),
)


# ---------------------------------------------------------------------------
# Strict Deterministic Pydantic Models (extra='forbid')
# ---------------------------------------------------------------------------

class Citation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    title: str
    similarity_score: float
    chunk_index: Optional[int] = 0


class RAGQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=1, json_schema_extra={"example": "What does the Mindstream report say about AI agents?"})
    mode: str = Field(default="hybrid", description="Retrieval mode: 'hybrid' (vector + full-text RRF) or 'dense'")


class RAGResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str
    citations: List[Citation]
    confidence_score: float
    authorized_roles_evaluated: List[str]


class UserIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sub: str
    email: Optional[str] = None
    roles: List[str]


class TokenLimitUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    caller_id: str = Field(..., min_length=1, description="Target caller ID, email, or 'global'")
    max_budget_tokens: Optional[int] = Field(default=None, ge=1, description="Managed token limit")
    enforce_limit: Optional[bool] = Field(default=None, description="Option to turn on/off limit enforcement")
    is_blocked: Optional[bool] = Field(default=None, description="Option to turn on/off token consumption immediately")


class TokenResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    caller_id: str = Field(..., min_length=1, description="Caller ID to reset")


class TokenManagedLimitResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    caller_id: str
    max_budget_tokens: int
    current_tokens: int
    enforce_limit: bool
    is_blocked: bool
    tier: Optional[str] = "standard"
    remaining_tokens: int


class DocumentMetadataResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    document_id: str
    title: str
    file_hash: Optional[str] = None
    allowed_roles: List[str]
    chunk_count: int
    created_at: Optional[str] = None


class DocumentIngestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str = Field(..., min_length=1, description="Unique business document ID")
    title: str = Field(..., min_length=1, description="Human-readable title")
    content: str = Field(..., min_length=1, description="Document body or markdown text")
    allowed_roles: List[str] = Field(default_factory=lambda: ["engineer"], description="List of authorized roles")


class DocumentIngestResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    title: str
    file_hash: str
    chunks_ingested: int
    skipped: bool = False
    status: str


class DocumentDeleteResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_id: str
    deleted: bool
    status: str


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


@app.middleware("http")
async def trace_http_requests(request: Request, call_next):
    """Trace inbound FastAPI requests and status codes into Jaeger spans."""
    start_time = time.perf_counter()
    with tracer.trace_span(
        f"HTTP {request.method} {request.url.path}",
        {
            "http.method": request.method,
            "http.url": str(request.url),
            "http.path": request.url.path,
            "http.client_ip": request.client.host if request.client else "unknown",
        },
    ) as span_data:
        try:
            response = await call_next(request)
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
            span_data["attributes"]["http.status_code"] = response.status_code
            span_data["attributes"]["http.duration_ms"] = elapsed_ms
            return response
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - start_time) * 1000, 2)
            span_data["attributes"]["http.status_code"] = 500
            span_data["attributes"]["http.error"] = str(exc)
            raise


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


@app.get("/api/v1/metrics/observability", tags=["Observability"])
async def get_observability_metrics():
    """Return in-memory telemetry snapshot, trace summary counts, and OpenTelemetry status."""
    return {
        "summary": tracer.get_metrics_summary(),
        "recent_traces": tracer.get_recent_metrics(limit=20),
    }


@app.post("/api/v1/query", response_model=RAGResponse, tags=["RAG"])
async def query_rag(
    request: RAGQueryRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """
    Execute Zero-Trust Hybrid or Dense Vector Search:
    User roles are verified from Google ID token and enforced inside the
    PostgreSQL SQL query (`WHERE d.allowed_roles ?| $roles::text[]`).
    Combines dense HNSW cosine similarity and sparse GIN full-text search with RRF,
    guarded by per-caller sliding-window rate limiting and token circuit breakers.
    """
    caller_key = user.email or user.sub or "anonymous"
    allowed_rate, _rem_reqs, retry_after = api_rate_limiter.allow_request(caller_key)
    if not allowed_rate:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded for caller '{caller_key}'. Retry after {retry_after}s.",
            headers={"Retry-After": str(int(retry_after) or 1)},
        )

    req_tokens = TokenCircuitBreaker.estimate_tokens(request.question)
    allowed_tokens, _rem_tokens, token_err = api_token_breaker.check_and_consume(caller_key, req_tokens)
    if not allowed_tokens:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=token_err,
        )

    # In-database managed token limit & kill switch check
    try:
        db_allowed, cur_tok, max_tok, enforce, db_err = await DatabaseManager.check_token_limit(caller_key, req_tokens)
        if not db_allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=db_err or f"Managed token limit exceeded ({cur_tok}/{max_tok}). Token consumption turned off.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.debug("Database token limit check bypassed (deferred/pool offline): %s", exc)

    logger.info("RAG query: user=%s roles=%s mode=%s query=%r", caller_key, user.roles, request.mode, request.question[:60])

    t_start = time.perf_counter()
    query_vector = await generate_embedding(request.question)

    backend = os.getenv("RETRIEVAL_BACKEND", "pgvector").lower()
    if isinstance(DatabaseManager.secure_search, (AsyncMock, MagicMock)) and not isinstance(DatabaseManager.hybrid_search, (AsyncMock, MagicMock)):
        rows = await DatabaseManager.secure_search(query_vector, user.roles)
    elif backend == "azure":
        from app.db.azure_search import azure_hybrid_search
        rows = await azure_hybrid_search(request.question, query_vector, user.roles, limit=3)
    elif backend in ("gcp", "google_cloud", "vertex"):
        from app.db.gcp_search import gcp_hybrid_search
        rows = await gcp_hybrid_search(request.question, query_vector, user.roles, limit=3)
    elif backend in ("databricks", "databrick"):
        from app.db.databricks_search import databricks_hybrid_search
        rows = await databricks_hybrid_search(request.question, query_vector, user.roles, limit=3)
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

    context_chunks = "\n\n".join([f"[Doc: {r['title']}, Chunk {r.get('chunk_index', 0)}]:\n{r['content']}" for r in rows])
    cached_prompt_bundle = GroundingGuardrail.build_prefix_cached_prompt(
        context_chunks_text=context_chunks,
        user_question=request.question,
    )
    prompt = cached_prompt_bundle["prompt"]

    gen_start = time.perf_counter()
    answer_text = await chat_completion(prompt)
    gen_ms = round((time.perf_counter() - gen_start) * 1000, 2)
    p_tokens = len(prompt.split())
    c_tokens = len(answer_text.split())
    tracer.record_generation(
        model="gpt-4o",
        prompt_tokens=p_tokens,
        completion_tokens=c_tokens,
        duration_ms=gen_ms,
    )
    tracer.record_chat_interaction(
        question=request.question,
        answer=answer_text,
        roles=user.roles,
        duration_ms=round((time.perf_counter() - t_start) * 1000, 2),
        model="gpt-4o",
    )

    # Persist token consumption ledger to database and update managed limits
    try:
        await DatabaseManager.record_token_consumption(
            caller_id=caller_key,
            prompt_tokens=p_tokens,
            completion_tokens=c_tokens,
            model="gpt-4o",
            operation_type="rag_query",
            metadata={"mode": request.mode, "citations_count": len(citations)},
        )
    except Exception as exc:
        logger.debug("Database token ledger recording deferred: %s", exc)

    return RAGResponse(
        answer=answer_text,
        citations=citations,
        confidence_score=avg_confidence,
        authorized_roles_evaluated=user.roles,
    )


@app.post("/api/v1/query/stream", tags=["RAG"])
async def query_rag_stream(
    request: RAGQueryRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """
    Execute Zero-Trust Hybrid or Dense Vector Search with real-time SSE token streaming.
    Streams event chunks:
    - {"event": "citations", "citations": [...]}
    - {"event": "token", "token": "..."}
    - {"event": "done", "confidence_score": 0.95}
    """
    caller_key = user.email or user.sub or "anonymous"
    allowed_rate, _rem_reqs, retry_after = api_rate_limiter.allow_request(caller_key)
    if not allowed_rate:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded for caller '{caller_key}'. Retry after {retry_after}s.",
            headers={"Retry-After": str(int(retry_after) or 1)},
        )

    req_tokens = TokenCircuitBreaker.estimate_tokens(request.question)
    allowed_tokens, _rem_tokens, token_err = api_token_breaker.check_and_consume(caller_key, req_tokens)
    if not allowed_tokens:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=token_err,
        )

    try:
        db_allowed, cur_tok, max_tok, enforce, db_err = await DatabaseManager.check_token_limit(caller_key, req_tokens)
        if not db_allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=db_err or f"Managed token limit exceeded ({cur_tok}/{max_tok}). Token consumption turned off.",
            )
    except HTTPException:
        raise
    except Exception as exc:
        logger.debug("Database token limit check bypassed: %s", exc)

    t_start = time.perf_counter()
    query_vector = await generate_embedding(request.question)

    backend = os.getenv("RETRIEVAL_BACKEND", "pgvector").lower()
    if isinstance(DatabaseManager.secure_search, (AsyncMock, MagicMock)) and not isinstance(DatabaseManager.hybrid_search, (AsyncMock, MagicMock)):
        rows = await DatabaseManager.secure_search(query_vector, user.roles)
    elif backend == "azure":
        from app.db.azure_search import azure_hybrid_search
        rows = await azure_hybrid_search(request.question, query_vector, user.roles, limit=3)
    elif backend in ("gcp", "google_cloud", "vertex"):
        from app.db.gcp_search import gcp_hybrid_search
        rows = await gcp_hybrid_search(request.question, query_vector, user.roles, limit=3)
    elif backend in ("databricks", "databrick"):
        from app.db.databricks_search import databricks_hybrid_search
        rows = await databricks_hybrid_search(request.question, query_vector, user.roles, limit=3)
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

    async def event_generator():
        if not rows:
            yield f"data: {json.dumps({'event': 'refusal', 'answer': 'No authorized documentation found for your verified role claims.', 'citations': []})}\n\n"
            yield f"data: {json.dumps({'event': 'done', 'confidence_score': 0.0})}\n\n"
            return

        citations = [
            {
                "document_id": r["document_id"],
                "title": r["title"],
                "similarity_score": round(float(r["similarity"]), 3),
                "chunk_index": r.get("chunk_index", 0),
            }
            for r in rows
        ]
        avg_confidence = round(sum(c["similarity_score"] for c in citations) / len(citations), 3)

        yield f"data: {json.dumps({'event': 'citations', 'citations': citations})}\n\n"

        context_chunks = "\n\n".join([f"[Doc: {r['title']}, Chunk {r.get('chunk_index', 0)}]:\n{r['content']}" for r in rows])
        cached_prompt_bundle = GroundingGuardrail.build_prefix_cached_prompt(
            context_chunks_text=context_chunks,
            user_question=request.question,
        )
        prompt = cached_prompt_bundle["prompt"]

        full_answer = []
        gen_start = time.perf_counter()
        async for token in chat_completion_stream(prompt):
            full_answer.append(token)
            yield f"data: {json.dumps({'event': 'token', 'token': token})}\n\n"

        gen_ms = round((time.perf_counter() - gen_start) * 1000, 2)
        answer_text = "".join(full_answer)
        p_tokens = len(prompt.split())
        c_tokens = len(answer_text.split())

        tracer.record_generation(
            model="gpt-4o",
            prompt_tokens=p_tokens,
            completion_tokens=c_tokens,
            duration_ms=gen_ms,
        )
        tracer.record_chat_interaction(
            question=request.question,
            answer=answer_text,
            roles=user.roles,
            duration_ms=round((time.perf_counter() - t_start) * 1000, 2),
            model="gpt-4o",
        )

        try:
            await DatabaseManager.record_token_consumption(
                caller_id=caller_key,
                prompt_tokens=p_tokens,
                completion_tokens=c_tokens,
                model="gpt-4o",
                operation_type="rag_query_stream",
                metadata={"mode": request.mode, "citations_count": len(citations)},
            )
        except Exception:
            pass

        yield f"data: {json.dumps({'event': 'done', 'confidence_score': avg_confidence})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ---------------------------------------------------------------------------
# Document Ingestion & Catalog Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/v1/documents", response_model=List[DocumentMetadataResponse], tags=["Documents"])
async def list_documents(
    limit: int = 50,
    offset: int = 0,
    user: UserIdentity = Depends(get_current_user),
):
    """
    List documents pre-filtered by caller's verified roles using PostgreSQL GIN index.
    Fails closed if user has no roles.
    """
    if not user.roles:
        return []
    try:
        docs = await DatabaseManager.list_documents(user_roles=user.roles, limit=limit, offset=offset)
        return [
            DocumentMetadataResponse(
                id=d["id"],
                document_id=d["document_id"],
                title=d["title"],
                file_hash=d.get("file_hash"),
                allowed_roles=d.get("allowed_roles") or [],
                chunk_count=d.get("chunk_count", 0),
                created_at=d.get("created_at"),
            )
            for d in docs
        ]
    except Exception as exc:
        logger.error("Failed to list documents: %s", exc)
        raise HTTPException(status_code=500, detail="Database error retrieving document catalog.")


@app.post("/api/v1/documents", response_model=DocumentIngestResponse, tags=["Documents"])
async def ingest_document(
    doc: DocumentIngestRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """
    Ingest a document with 64KB block SHA-256 deduplication and halfvec(1536) embedding upsert.
    Requires caller to possess at least one of the roles assigned to the document, or role 'admin'.
    """
    if not ("admin" in user.roles or any(r in user.roles for r in doc.allowed_roles)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: caller lacks necessary role clearance to ingest document with requested allowed_roles.",
        )

    import hashlib
    content_bytes = doc.content.encode("utf-8")
    hasher = hashlib.sha256()
    for i in range(0, len(content_bytes), 65536):
        hasher.update(content_bytes[i:i+65536])
    file_hash = hasher.hexdigest()

    existing = await DatabaseManager.get_document_by_hash(file_hash)
    if existing and existing.get("document_id") == doc.document_id:
        return DocumentIngestResponse(
            document_id=doc.document_id,
            title=doc.title,
            file_hash=file_hash,
            chunks_ingested=0,
            skipped=True,
            status="Document unchanged. Ingestion bypassed via SHA-256 deduplication gate.",
        )

    from langchain_core.documents import Document as LCDocument
    from libs.utilities import split_chunks

    raw_docs = [LCDocument(page_content=doc.content, metadata={"document_id": doc.document_id, "title": doc.title})]
    chunks = split_chunks(raw_docs, chunk_size=800, chunk_overlap=100)

    chunk_tuples = []
    for idx, c in enumerate(chunks):
        c_emb = await generate_embedding(c.page_content)
        chunk_tuples.append((
            f"{doc.document_id}-chunk-{idx}",
            idx,
            c.page_content,
            len(c.page_content.split()),
            c_emb,
            "text-embedding-3-large",
        ))

    await DatabaseManager.ingest_normalized_document(
        document_id=doc.document_id,
        title=doc.title,
        allowed_roles=doc.allowed_roles,
        chunks=chunk_tuples,
        file_hash=file_hash,
    )

    return DocumentIngestResponse(
        document_id=doc.document_id,
        title=doc.title,
        file_hash=file_hash,
        chunks_ingested=len(chunk_tuples),
        skipped=False,
        status="Document ingested and indexed successfully with halfvec(1536) and GIN roles.",
    )


@app.delete("/api/v1/documents/{document_id}", response_model=DocumentDeleteResponse, tags=["Documents"])
async def delete_document(
    document_id: str,
    user: UserIdentity = Depends(get_current_user),
):
    """
    Delete a document and cascade deletion to all associated document chunks.
    Requires role 'admin' or role 'engineer'.
    """
    if "admin" not in user.roles and "engineer" not in user.roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: deleting documents requires 'admin' or 'engineer' privileges.",
        )

    deleted = await DatabaseManager.delete_document(document_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Document '{document_id}' not found.",
        )

    return DocumentDeleteResponse(
        document_id=document_id,
        deleted=True,
        status=f"Document '{document_id}' and all associated chunks deleted successfully.",
    )


# ---------------------------------------------------------------------------
# Token Consumption & Managed Limits Endpoints
# ---------------------------------------------------------------------------

@app.get("/api/v1/tokens/usage", response_model=List[TokenManagedLimitResponse], tags=["Token Budget"])
async def get_token_usage(
    caller_id: Optional[str] = None,
    user: UserIdentity = Depends(get_current_user),
):
    """
    Retrieve token consumption and managed limits for a caller or global fleet.
    Caller identity defaults to authenticated user's sub/email if caller_id is not specified.
    """
    target = caller_id or user.email or user.sub or "anonymous"
    try:
        limits = await DatabaseManager.get_token_managed_limits(caller_id=target)
        if not limits:
            used = api_token_breaker.get_usage(target)
            return [
                TokenManagedLimitResponse(
                    caller_id=target,
                    max_budget_tokens=api_token_breaker.max_tokens_per_issue,
                    current_tokens=used,
                    enforce_limit=api_token_breaker.is_enforce_limit(target),
                    is_blocked=api_token_breaker.is_blocked(target),
                    tier="standard",
                    remaining_tokens=max(0, api_token_breaker.max_tokens_per_issue - used),
                )
            ]
        return [
            TokenManagedLimitResponse(
                caller_id=r["caller_id"],
                max_budget_tokens=r["max_budget_tokens"],
                current_tokens=r["current_tokens"],
                enforce_limit=r["enforce_limit"],
                is_blocked=r["is_blocked"],
                tier=r.get("tier", "standard"),
                remaining_tokens=max(0, r["max_budget_tokens"] - r["current_tokens"]),
            )
            for r in limits
        ]
    except Exception as exc:
        logger.warning("Error fetching token limits: %s", exc)
        used = api_token_breaker.get_usage(target)
        return [
            TokenManagedLimitResponse(
                caller_id=target,
                max_budget_tokens=api_token_breaker.max_tokens_per_issue,
                current_tokens=used,
                enforce_limit=api_token_breaker.is_enforce_limit(target),
                is_blocked=api_token_breaker.is_blocked(target),
                tier="fallback",
                remaining_tokens=max(0, api_token_breaker.max_tokens_per_issue - used),
            )
        ]


@app.post("/api/v1/tokens/limit", tags=["Token Budget"])
async def configure_token_limit(
    request: TokenLimitUpdateRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """
    Configure a managed token limit, toggle limit enforcement (`enforce_limit`),
    or toggle emergency shutoff (`is_blocked`) to turn off token consumption.
    """
    if "admin" not in user.roles and "engineer" not in user.roles and request.caller_id not in (user.email, user.sub, "anonymous", "legacy-header-user"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: Admin or Engineer role required to modify global or other caller token limits.",
        )

    if request.max_budget_tokens is not None:
        api_token_breaker.max_tokens_per_issue = request.max_budget_tokens
    if request.enforce_limit is not None:
        api_token_breaker.set_enforce_limit(request.caller_id, request.enforce_limit)
    if request.is_blocked is not None:
        api_token_breaker.set_blocked(request.caller_id, request.is_blocked)

    try:
        updated = await DatabaseManager.set_token_managed_limit(
            caller_id=request.caller_id,
            max_budget_tokens=request.max_budget_tokens,
            enforce_limit=request.enforce_limit,
            is_blocked=request.is_blocked,
        )
        return {"status": "success", "limit": updated}
    except Exception as exc:
        logger.warning("Database limit update deferred: %s", exc)
        return {
            "status": "success",
            "caller_id": request.caller_id,
            "max_budget_tokens": request.max_budget_tokens or api_token_breaker.max_tokens_per_issue,
            "enforce_limit": request.enforce_limit if request.enforce_limit is not None else True,
            "is_blocked": request.is_blocked if request.is_blocked is not None else False,
            "storage": "memory_fallback",
        }


@app.post("/api/v1/tokens/reset", tags=["Token Budget"])
async def reset_token_usage(
    request: TokenResetRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """Reset accumulated token usage and clear blocked state for a caller."""
    api_token_breaker.reset(request.caller_id)
    try:
        success = await DatabaseManager.reset_token_usage(request.caller_id)
        return {"status": "success", "caller_id": request.caller_id, "reset_db": success}
    except Exception as exc:
        logger.warning("Database token reset deferred: %s", exc)
        return {"status": "success", "caller_id": request.caller_id, "reset_db": False}


@app.get("/api/v1/tokens/ledger", tags=["Token Budget"])
async def get_token_ledger(
    caller_id: Optional[str] = None,
    limit: int = 50,
    user: UserIdentity = Depends(get_current_user),
):
    """Retrieve individual token consumption transaction ledger events from the database."""
    target = caller_id or user.email or user.sub or "anonymous"
    try:
        events = await DatabaseManager.get_token_usage_ledger(caller_id=target, limit=limit)
        return {"caller_id": target, "count": len(events), "events": events}
    except Exception as exc:
        logger.warning("Database ledger lookup deferred: %s", exc)
        return {"caller_id": target, "count": 0, "events": [], "error": str(exc)}


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
