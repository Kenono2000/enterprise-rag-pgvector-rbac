"""
scripts/set_firebase_claims.py
------------------------------
One-shot CLI tool to set (or clear) app_roles custom claims on a Firebase user.

Usage
-----
# Assign roles to a user by UID
python scripts/set_firebase_claims.py --uid abc123 --roles engineer hr_manager

# Assign roles by email (looks up the UID automatically)
python scripts/set_firebase_claims.py --email alice@acme.com --roles finance_executive

# Show current claims for a user
python scripts/set_firebase_claims.py --email alice@acme.com --show

# Clear all app_roles claims for a user
python scripts/set_firebase_claims.py --uid abc123 --clear

# Bulk-assign from a CSV file (see scripts/sample_roles.csv)
python scripts/set_firebase_claims.py --csv scripts/sample_roles.csv

Prerequisites
-------------
1. Download your Firebase service account key:
      Firebase Console → Project Settings → Service accounts → Generate new private key
      Save it as  firebase-service-account.json  (already in .gitignore)

2. Set the path in your environment (or pass via --creds):
      $env:GOOGLE_APPLICATION_CREDENTIALS = "C:\\path\\to\\firebase-service-account.json"
   OR pass directly:
      python scripts/set_firebase_claims.py --creds firebase-service-account.json ...
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys

# Force UTF-8 output on Windows terminals (avoids cp1252 UnicodeEncodeError)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import firebase_admin
from firebase_admin import auth, credentials

# ---------------------------------------------------------------------------
# Allowed role values (must match PostgreSQL allowed_roles values)
# ---------------------------------------------------------------------------
KNOWN_ROLES = {
    "finance_executive",
    "compliance_auditor",
    "hr_manager",
    "executive",
    "engineer",
}


# ---------------------------------------------------------------------------
# Firebase init
# ---------------------------------------------------------------------------

def init_firebase(creds_path: str | None = None) -> None:
    if firebase_admin._apps:
        return  # already initialised

    creds_path = creds_path or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds_path:
        sys.exit(
            "[ERROR]  No credentials found.\n"
            "         Set GOOGLE_APPLICATION_CREDENTIALS or pass --creds <path>."
        )

    cred = credentials.Certificate(creds_path)
    firebase_admin.initialize_app(cred)
    print(f"[OK]  Firebase initialised with: {creds_path}")


# ---------------------------------------------------------------------------
# Helper: resolve UID from email
# ---------------------------------------------------------------------------

def uid_from_email(email: str) -> str:
    user = auth.get_user_by_email(email)
    return user.uid


# ---------------------------------------------------------------------------
# Core operations
# ---------------------------------------------------------------------------

def show_claims(uid: str) -> None:
    user = auth.get_user(uid)
    claims = user.custom_claims or {}
    print(f"\n[USER]  uid   : {uid}")
    print(f"        email : {user.email}")
    print(f"        claims: {json.dumps(claims, indent=2)}")


def set_roles(uid: str, roles: list[str]) -> None:
    # Validate
    unknown = set(roles) - KNOWN_ROLES
    if unknown:
        sys.exit(f"[ERROR]  Unknown roles: {unknown}\n         Valid roles: {KNOWN_ROLES}")

    auth.set_custom_user_claims(uid, {"app_roles": roles})
    print(f"[OK]  Set app_roles={roles} for uid={uid}")
    print(
        "[NOTE] The user must sign out and sign back in (or the ID token must expire)\n"
        "       before the new claims appear in their token."
    )


def clear_roles(uid: str) -> None:
    auth.set_custom_user_claims(uid, {"app_roles": []})
    print(f"[OK]  Cleared app_roles for uid={uid}")


def bulk_from_csv(csv_path: str) -> None:
    """
    CSV format (with header row):
        email,roles
        alice@acme.com,"engineer,hr_manager"
        bob@acme.com,finance_executive
    """
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    print(f"[INFO]  Processing {len(rows)} rows from {csv_path}...\n")
    errors = []
    for row in rows:
        email = row.get("email", "").strip()
        raw_roles = row.get("roles", "").strip()
        roles = [r.strip() for r in raw_roles.split(",") if r.strip()]
        if not email:
            continue
        try:
            uid = uid_from_email(email)
            set_roles(uid, roles)
        except Exception as exc:
            errors.append(f"  {email}: {exc}")
            print(f"[ERROR]  {email}: {exc}")

    if errors:
        print(f"\n[WARN]  {len(errors)} error(s) during bulk import.")
    else:
        print(f"\n[DONE]  All {len(rows)} users updated successfully.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Set Firebase custom claims (app_roles) for RAG RBAC",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--creds", help="Path to Firebase service account JSON key file")

    # Target user (mutually exclusive)
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--uid", help="Firebase UID of the user")
    target.add_argument("--email", help="Email address (UID is looked up automatically)")
    target.add_argument("--csv", metavar="CSV_FILE", help="Bulk-assign roles from a CSV file")

    # Action
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--roles", nargs="+", metavar="ROLE", help="Roles to assign")
    action.add_argument("--clear", action="store_true", help="Remove all app_roles claims")
    action.add_argument("--show", action="store_true", help="Print current claims and exit")

    args = parser.parse_args()

    init_firebase(args.creds)

    # --- Bulk CSV mode ---
    if args.csv:
        bulk_from_csv(args.csv)
        return

    # --- Single-user mode ---
    if not args.uid and not args.email:
        parser.error("Provide --uid, --email, or --csv")

    uid = args.uid or uid_from_email(args.email)

    if args.show:
        show_claims(uid)
    elif args.clear:
        clear_roles(uid)
    elif args.roles:
        set_roles(uid, args.roles)
    else:
        parser.error("Provide one of --roles, --clear, or --show")


if __name__ == "__main__":
    main()
