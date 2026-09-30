"""
scripts/firebase_onuser_create_function.py
------------------------------------------
Firebase Cloud Function (2nd gen, Python) that automatically assigns
app_roles custom claims when a new user signs up via Google OAuth.

Deploy
------
  firebase deploy --only functions

Or with the gcloud CLI:
  gcloud functions deploy assign_roles_on_create \
    --gen2 \
    --runtime python312 \
    --trigger-event-filters="type=google.firebase.auth.user.v1.created" \
    --entry-point assign_roles_on_create \
    --region us-central1 \
    --set-env-vars ROLE_MAP='{"@acme.com":["engineer"],"cfo@acme.com":["finance_executive","executive"]}'

Environment variables
---------------------
ROLE_MAP   JSON object mapping email pattern → list of roles.
           Pattern rules:
             "@domain.com"  matches any email ending with that domain
             "user@x.com"   exact email match

           Example:
             {"@acme.com": ["engineer"], "cfo@acme.com": ["finance_executive"]}

This file also doubles as a standalone local admin script — see __main__ below.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Known roles (must match PostgreSQL allowed_roles values)
# ---------------------------------------------------------------------------

KNOWN_ROLES = {
    "finance_executive",
    "compliance_auditor",
    "hr_manager",
    "executive",
    "engineer",
}


# ---------------------------------------------------------------------------
# Role resolution
# ---------------------------------------------------------------------------

def _resolve_roles(email: str) -> list[str]:
    """
    Look up the email in the ROLE_MAP env variable and return matching roles.
    More specific patterns (exact match) take priority over domain patterns.
    """
    raw = os.getenv("ROLE_MAP", "{}")
    try:
        role_map: dict[str, list[str]] = json.loads(raw)
    except json.JSONDecodeError:
        logger.error("ROLE_MAP is not valid JSON: %s", raw)
        return []

    email_lower = email.lower()
    exact_roles: list[str] = []
    domain_roles: list[str] = []

    for pattern, roles in role_map.items():
        pattern_lower = pattern.lower()
        if email_lower == pattern_lower:
            exact_roles.extend(roles)
        elif pattern_lower.startswith("@") and email_lower.endswith(pattern_lower):
            domain_roles.extend(roles)

    combined = list(set(exact_roles or domain_roles))
    return [r for r in combined if r in KNOWN_ROLES]


# ---------------------------------------------------------------------------
# Cloud Function entry point (Firebase Auth trigger)
# ---------------------------------------------------------------------------

def assign_roles_on_create(event: Any, context: Any = None) -> None:
    """
    Triggered by Firebase Auth "user created" event.
    Works with both Firebase Functions v1 (background) and v2 (CloudEvent).
    """
    # Support both v1 dict payload and v2 CloudEvent
    if hasattr(event, "data"):
        data = event.data  # v2 CloudEvent
    elif isinstance(event, dict):
        data = event       # v1 background function
    else:
        logger.error("Unexpected event type: %s", type(event))
        return

    uid: str = data.get("uid", "")
    email: str = data.get("email", "")

    if not uid:
        logger.warning("Event missing uid, skipping")
        return

    roles = _resolve_roles(email)
    logger.info("User created: uid=%s email=%s → roles=%s", uid, email, roles)

    if not roles:
        logger.info("No roles resolved for %s — skipping claim write", email)
        return

    # Import firebase_admin here so the module can be imported without it
    # (useful when unit-testing _resolve_roles in isolation)
    import firebase_admin
    from firebase_admin import auth, credentials

    if not firebase_admin._apps:
        firebase_admin.initialize_app()  # uses GOOGLE_APPLICATION_CREDENTIALS / ADC

    auth.set_custom_user_claims(uid, {"app_roles": roles})
    logger.info("✅  Set app_roles=%s for uid=%s", roles, uid)


# ---------------------------------------------------------------------------
# Local admin usage: python scripts/firebase_onuser_create_function.py
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Simulate the on-user-create trigger locally for testing"
    )
    parser.add_argument("--uid", required=True, help="Firebase UID")
    parser.add_argument("--email", required=True, help="User email")
    parser.add_argument(
        "--creds",
        help="Path to Firebase service account JSON (or set GOOGLE_APPLICATION_CREDENTIALS)",
    )
    args = parser.parse_args()

    if args.creds:
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = args.creds

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    assign_roles_on_create({"uid": args.uid, "email": args.email})
