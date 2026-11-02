"""
conftest.py
-----------
Root pytest bootstrap that guarantees hermetic, 100% offline test execution.

The repository ships a developer ``.env`` that points at *live* infrastructure
(PostgreSQL, a hosted OTLP/Honeycomb collector, cloud vector stores, a GitHub
token). Importing application modules calls ``load_dotenv(..., override=False)``,
which means any variable pinned here stays authoritative.

Why this file exists
--------------------
1. ``app/observability.py`` initialises a real ``OTLPSpanExporter`` when
   ``OTEL_ENABLED=true``. With a developer ``.env`` present that would stream
   spans (and credentials) to an external collector during unit tests, and the
   ``BatchSpanProcessor`` flush on interpreter shutdown can block for a long
   time when egress is unavailable.
2. ``DATABASE_URL`` / ``GITHUB_TOKEN`` from a developer ``.env`` would make tests
   attempt real network I/O instead of exercising their mocks.
3. Optional heavyweight SDKs (``crewai``) are imported lazily and only when
   explicitly enabled, so discovery/triage paths stay deterministic.

Pinned values are intentionally minimal: only egress-causing and non-deterministic
settings are neutralised; per-test ``monkeypatch.setenv`` calls still take
precedence because they run later.
"""

from __future__ import annotations

import os

# --- Offline / deterministic test environment -----------------------------
# Applied at import time, before pytest imports any test module (and therefore
# before any application module).
_TEST_ENV = {
    # Never stream telemetry to an external collector from a test run.
    "OTEL_ENABLED": "false",
    "APPLICATIONINSIGHTS_CONNECTION_STRING": "",
    "OTEL_EXPORTER_OTLP_ENDPOINT": "",
    "OTEL_EXPORTER_OTLP_INSECURE": "true",
    # No live database or issue-tracker I/O; tests inject mocks instead.
    "DATABASE_URL": "",
    "GITHUB_TOKEN": "",
    # `role_mapper._init_firebase_admin()` falls back to Application Default
    # Credentials, which probes the GCE metadata server (169.254.169.254) and can
    # block for ~25s when it is unreachable. An explicit path to a non-existent
    # file makes google.auth raise immediately, keeping the run offline and fast.
    "GOOGLE_APPLICATION_CREDENTIALS": os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "_no_test_credentials.json"
    ),
    # No live LLM provider credentials: tests must never make billable API calls.
    # With these blank, `app/db/llm.py` takes its deterministic local-mock branch.
    "OPENAI_API_KEY": "",
    "AZURE_OPENAI_API_KEY": "",
    "GEMINI_API_KEY": "",
    # Deterministic auth/backend defaults (individual tests override these).
    "ENVIRONMENT": "test",
    "REQUIRE_GOOGLE_AUTH": "false",
    "RETRIEVAL_BACKEND": "pgvector",
    # The SDLC agent must never push or open PRs during tests.
    "SDLC_PUSH": "false",
    # Opt-in only: importing the real CrewAI SDK is a heavyweight, side-effecting
    # import. Tests that exercise the SDK adapter inject a fake module explicitly.
    "USE_CREWAI_SDK": "false",
}

for _key, _value in _TEST_ENV.items():
    os.environ[_key] = _value
