"""
app/api/rag.py
--------------
FastAPI router for the Zero-Trust RAG endpoint.

Authentication
--------------
Accepts Google / Firebase ID tokens via the standard Bearer scheme:

    Authorization: Bearer <id_token>

The token is verified against Google's public JWKS (RS256) and the caller's
application roles are extracted from the ``app_roles`` Firebase custom claim
(see app/auth/role_mapper.py).

Backward-compatibility / local dev
-----------------------------------
If no Authorization header is present AND the request includes the legacy
``X-User-Roles`` header, the legacy header is honoured so that existing tests
and demo scripts continue to work.  This fallback is disabled in production
by setting the ``REQUIRE_GOOGLE_AUTH=true`` environment variable.
"""

from __future__ import annotations

import json
import logging
import os
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field

from app.auth.jwks import verify_google_token
from app.auth.role_mapper import extract_roles, KNOWN_ROLES
from app.db.llm import chat_completion, generate_embedding
from app.db.manager import DatabaseManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1")

# ---------------------------------------------------------------------------
# Security scheme
# ---------------------------------------------------------------------------

bearer_scheme = HTTPBearer(auto_error=False)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------


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


class UserIdentity(BaseModel):
    sub: str
    email: Optional[str] = None
    roles: List[str]


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(bearer_scheme),
    x_user_roles: Optional[str] = Header(default=None),
) -> UserIdentity:
    """
    Resolve the caller's identity and application roles.

    Verification priority:
    1. ``Authorization: Bearer <google_id_token>`` — verified via Google JWKS.
    2. ``X-User-Roles`` legacy header — only when REQUIRE_GOOGLE_AUTH is not "true".
    """
    require_google = os.getenv("REQUIRE_GOOGLE_AUTH", "false").lower() == "true"

    # --- Path 1: Bearer token ---
    if credentials and credentials.credentials:
        try:
            payload = verify_google_token(credentials.credentials)
        except Exception as exc:
            logger.warning("Token verification failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired Google ID token",
                headers={"WWW-Authenticate": "Bearer"},
            ) from exc

        roles = extract_roles(payload)
        return UserIdentity(
            sub=payload["sub"],
            email=payload.get("email"),
            roles=roles,
        )

    # --- Path 2: Legacy X-User-Roles header (dev / backward-compat) ---
    if not require_google and x_user_roles:
        try:
            raw_roles = json.loads(x_user_roles)
            if not isinstance(raw_roles, list):
                raise ValueError("X-User-Roles must be a JSON array")
            roles = [
                str(r).strip() for r in raw_roles 
                if isinstance(r, str) and (r.strip() in KNOWN_ROLES or r.strip().isidentifier())
            ]
            logger.debug("Using legacy X-User-Roles header: %s", roles)
            return UserIdentity(sub="legacy-header-user", roles=roles)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid X-User-Roles header: {exc}",
            ) from exc

    # --- Path 3: No credentials ---
    if require_google:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header with a Google ID token is required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Permissive default for local dev (no REQUIRE_GOOGLE_AUTH, no headers)
    logger.debug("No auth credentials provided — using empty role list (local dev)")
    return UserIdentity(sub="anonymous", roles=[])


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------


@router.post("/query", response_model=RAGResponse)
async def query_rag(
    request: RAGQueryRequest,
    user: UserIdentity = Depends(get_current_user),
):
    """
    Zero-Trust RAG query.

    The caller's roles (extracted from the verified Google ID token) are passed
    directly into the pgvector RBAC SQL filter — no post-processing step.
    """
    logger.info(
        "RAG query: sub=%s roles=%s question=%r",
        user.sub,
        user.roles,
        request.question[:80],
    )

    query_vector = await generate_embedding(request.question)
    rows = await DatabaseManager.secure_search(query_vector, user.roles)

    if not rows:
        return RAGResponse(
            answer="No authorized documentation found.",
            citations=[],
            confidence_score=0.0,
            authorized_roles_evaluated=user.roles,
        )

    citations = [
        Citation(
            document_id=r["document_id"],
            title=r["title"],
            similarity_score=round(float(r["similarity"]), 3),
        )
        for r in rows
    ]

    avg_confidence = round(
        sum(c.similarity_score for c in citations) / len(citations), 3
    )
    context_chunks = "\n\n".join(
        [f"[{r['title']}]: {r['content']}" for r in rows]
    )

    prompt = f"Answer strictly using context:\n\n{context_chunks}\n\nQuestion: {request.question}"
    answer_text = await chat_completion(prompt)

    return RAGResponse(
        answer=answer_text,
        citations=citations,
        confidence_score=avg_confidence,
        authorized_roles_evaluated=user.roles,
    )
