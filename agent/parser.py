"""
agent/parser.py
---------------
GitHub webhook payload parsing and HMAC-SHA256 signature verification.
"""

from __future__ import annotations

import hmac
import hashlib
from typing import Optional
from pydantic import BaseModel


class SDLCEvent(BaseModel):
    source: str
    event_type: str
    issue_id: str
    title: str
    description: str
    repository: str


def parse_github_webhook(payload: dict) -> SDLCEvent:
    """Transform GitHub webhook JSON payload to internal SDLCEvent."""
    action = payload.get("action", "opened")
    return SDLCEvent(
        source="github",
        event_type=f"issue_{action}",
        issue_id=str(payload["issue"]["number"]),
        title=payload["issue"]["title"],
        description=payload["issue"]["body"] or "",
        repository=payload["repository"]["full_name"],
    )


def verify_github_signature(
    body: bytes,
    signature: Optional[str],
    secret: Optional[str],
) -> bool:
    """Verify GitHub webhook X-Hub-Signature-256 header using HMAC-SHA256."""
    if not secret:
        return True
    if not signature or not signature.startswith("sha256="):
        return False
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature[7:], digest)
