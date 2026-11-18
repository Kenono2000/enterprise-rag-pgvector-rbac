"""
incident_agent/data.py
----------------------
Synthetic incident corpus with known ground-truth root causes.

Ten hand-authored incidents (Step 1 project addition) power the fixed triage
pipeline and are expanded to thirty for the replay eval suite (Step 6) by
permuting service/severity/time-of-day. Every incident carries the ground
truth needed to grade tool selection, arguments, and final answers.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from incident_agent.models import ChangeEvent, Incident, IncidentSeverity, LogEntry, MetricPoint

UTC = timezone.utc

# Deterministic base time so every run of the replay suite sees identical data.
_BASE = datetime(2026, 11, 16, 14, 0, 0, tzinfo=UTC)
# Public alias so tools can anchor deterministic lookback windows to the corpus clock.
BASE_TIME = _BASE


def _mins(n: int) -> datetime:
    return _BASE + timedelta(minutes=n)


# --- Ground-truth change events (the "last change" that caused each incident) ---

CHANGES: Dict[str, List[ChangeEvent]] = {
    "svc-payments": [
        ChangeEvent(
            change_id="CHG-1001", timestamp=_mins(-95), service="svc-payments",
            actor="ci-bot", kind="deploy",
            description="Deploy payments-api v2.14.0 (new 3DS auth path)",
        ),
    ],
    "svc-search": [
        ChangeEvent(
            change_id="CHG-2001", timestamp=_mins(-60), service="svc-search",
            actor="sre-jane", kind="config",
            description="Raised search indexer max_connections 20 -> 200",
        ),
    ],
    "svc-auth": [
        ChangeEvent(
            change_id="CHG-3001", timestamp=_mins(-40), service="svc-auth",
            actor="ci-bot", kind="deploy",
            description="Deploy auth-service v1.9.2 (JWT cache TTL change)",
        ),
    ],
    "svc-cart": [
        ChangeEvent(
            change_id="CHG-4001", timestamp=_mins(-130), service="svc-cart",
            actor="release-train", kind="deploy",
            description="Deploy cart-service v5.2.1 (cart merge logic)",
        ),
        ChangeEvent(
            change_id="CHG-4002", timestamp=_mins(-12), service="svc-cart",
            actor="sre-mike", kind="config",
            description="Toggled feature flag cart_merge_v2 to enabled",
        ),
    ],
    "svc-notify": [
        ChangeEvent(
            change_id="CHG-5001", timestamp=_mins(-200), service="svc-notify",
            actor="ci-bot", kind="deploy",
            description="Deploy notify-worker v0.31.0",
        ),
    ],
}

# --- Synthetic logs / metrics per service (bounded, deterministic) ---

_LOGS: Dict[str, List[LogEntry]] = {
    "svc-payments": [
        LogEntry(timestamp=_mins(-94), level="INFO", service="svc-payments", message="payments-api v2.14.0 started"),
        LogEntry(timestamp=_mins(-90), level="ERROR", service="svc-payments", message="3DS challenge loop: user redirected 5 times"),
        LogEntry(timestamp=_mins(-88), level="ERROR", service="svc-payments", message="3DS challenge loop: user redirected 5 times"),
        LogEntry(timestamp=_mins(-85), level="ERROR", service="svc-payments", message="payment intent abandoned after 3DS loop"),
    ],
    "svc-search": [
        LogEntry(timestamp=_mins(-59), level="INFO", service="svc-search", message="indexer config reload max_connections=200"),
        LogEntry(timestamp=_mins(-55), level="WARN", service="svc-search", message="connection pool exhausted (200/200)"),
        LogEntry(timestamp=_mins(-50), level="ERROR", service="svc-search", message="TooManyConnections: refusing query"),
        LogEntry(timestamp=_mins(-48), level="ERROR", service="svc-search", message="TooManyConnections: refusing query"),
    ],
    "svc-auth": [
        LogEntry(timestamp=_mins(-39), level="INFO", service="svc-auth", message="auth-service v1.9.2 started"),
        LogEntry(timestamp=_mins(-35), level="WARN", service="svc-auth", message="jwt cache TTL set to 0s (disabled)"),
        LogEntry(timestamp=_mins(-30), level="ERROR", service="svc-auth", message="JWKS fetch storm: 400 req/s to idp"),
    ],
    "svc-cart": [
        LogEntry(timestamp=_mins(-129), level="INFO", service="svc-cart", message="cart-service v5.2.1 started"),
        LogEntry(timestamp=_mins(-11), level="INFO", service="svc-cart", message="feature flag cart_merge_v2=enabled"),
        LogEntry(timestamp=_mins(-9), level="ERROR", service="svc-cart", message="cart merge produced duplicate line items"),
        LogEntry(timestamp=_mins(-8), level="ERROR", service="svc-cart", message="cart merge produced duplicate line items"),
    ],
    "svc-notify": [
        LogEntry(timestamp=_mins(-199), level="INFO", service="svc-notify", message="notify-worker v0.31.0 started"),
        LogEntry(timestamp=_mins(-180), level="WARN", service="svc-notify", message="queue depth rising: 12k pending"),
        LogEntry(timestamp=_mins(-170), level="ERROR", service="svc-notify", message="worker crash: null pointer in template render"),
    ],
}

_METRICS: Dict[str, List[MetricPoint]] = {
    "svc-payments": [
        MetricPoint(timestamp=_mins(-96), metric="http_5xx_rate", value=0.01, labels={"service": "svc-payments"}),
        MetricPoint(timestamp=_mins(-90), metric="http_5xx_rate", value=0.42, labels={"service": "svc-payments"}),
        MetricPoint(timestamp=_mins(-85), metric="http_5xx_rate", value=0.61, labels={"service": "svc-payments"}),
    ],
    "svc-search": [
        MetricPoint(timestamp=_mins(-61), metric="db_pool_utilization", value=0.30, labels={"service": "svc-search"}),
        MetricPoint(timestamp=_mins(-55), metric="db_pool_utilization", value=1.00, labels={"service": "svc-search"}),
        MetricPoint(timestamp=_mins(-48), metric="query_p99_ms", value=4200.0, labels={"service": "svc-search"}),
    ],
    "svc-auth": [
        MetricPoint(timestamp=_mins(-41), metric="jwks_fetch_rps", value=12.0, labels={"service": "svc-auth"}),
        MetricPoint(timestamp=_mins(-30), metric="jwks_fetch_rps", value=410.0, labels={"service": "svc-auth"}),
        MetricPoint(timestamp=_mins(-28), metric="http_5xx_rate", value=0.28, labels={"service": "svc-auth"}),
    ],
    "svc-cart": [
        MetricPoint(timestamp=_mins(-128), metric="cart_write_latency_p99_ms", value=120.0, labels={"service": "svc-cart"}),
        MetricPoint(timestamp=_mins(-9), metric="cart_write_latency_p99_ms", value=3800.0, labels={"service": "svc-cart"}),
        MetricPoint(timestamp=_mins(-7), metric="duplicate_line_items", value=1.0, labels={"service": "svc-cart"}),
    ],
    "svc-notify": [
        MetricPoint(timestamp=_mins(-198), metric="queue_depth", value=400.0, labels={"service": "svc-notify"}),
        MetricPoint(timestamp=_mins(-170), metric="queue_depth", value=12000.0, labels={"service": "svc-notify"}),
        MetricPoint(timestamp=_mins(-168), metric="worker_restart_count", value=3.0, labels={"service": "svc-notify"}),
    ],
}


def _incident(
    iid: str, service: str, title: str, severity: IncidentSeverity,
    fired_at_min: int, summary: str, runbook_hint: str,
    expected_change_id: str,
) -> Dict[str, Any]:
    """Build one incident dict with embedded ground truth for grading."""
    return {
        "incident": Incident(
            incident_id=iid,
            service=service,
            title=title,
            severity=severity,
            status="open",
            alert_fired_at=_mins(fired_at_min),
            summary=summary,
            runbook_hint=runbook_hint,
        ),
        "expected_change_id": expected_change_id,
        "expected_service": service,
    }


INCIDENTS: List[Dict[str, Any]] = [
    _incident(
        "INC-1001", "svc-payments", "Spike in payment 3DS challenge failures",
        IncidentSeverity.P1, -90,
        "Payments API 5xx rate jumped to 61% after the v2.14.0 deploy; users report being sent through 3DS repeatedly.",
        "Check the most recent deploy to svc-payments and correlate with the 3DS error logs.",
        "CHG-1001",
    ),
    _incident(
        "INC-1002", "svc-search", "Search query latency p99 over 4s",
        IncidentSeverity.P2, -50,
        "Search p99 latency breached 4s after the indexer connection-pool change; pool is pegged at 100%.",
        "Compare config changes to svc-search against db_pool_utilization.",
        "CHG-2001",
    ),
    _incident(
        "INC-1003", "svc-auth", "JWKS fetch storm to identity provider",
        IncidentSeverity.P1, -30,
        "auth-service is fetching JWKS at 410 req/s (baseline 12) after v1.9.2; the JWT cache appears disabled.",
        "Look for a config change disabling the JWT cache in the latest auth deploy.",
        "CHG-3001",
    ),
    _incident(
        "INC-1004", "svc-cart", "Duplicate line items after cart merge",
        IncidentSeverity.P2, -8,
        "Cart merges are producing duplicate line items right after the cart_merge_v2 flag was enabled.",
        "Correlate the feature-flag toggle with the deploy history on svc-cart.",
        "CHG-4002",
    ),
    _incident(
        "INC-1005", "svc-notify", "Notification queue depth at 12k",
        IncidentSeverity.P3, -170,
        "notify-worker queue depth climbed to 12k with repeated worker crashes in template rendering.",
        "Check worker restart counts and the last notify deploy.",
        "CHG-5001",
    ),
    # Variants 6-10: same root-cause families, different services/times/severities
    _incident(
        "INC-1006", "svc-payments", "3DS redirect loop during checkout",
        IncidentSeverity.P2, -88,
        "Checkout is looping customers through 3DS; payments 5xx elevated since the v2.14.0 rollout.",
        "Check recent payments deploys and 3DS error logs.",
        "CHG-1001",
    ),
    _incident(
        "INC-1007", "svc-search", "Connection pool exhaustion on search",
        IncidentSeverity.P1, -55,
        "Search indexer refuses queries: TooManyConnections after max_connections was raised to 200.",
        "Inspect svc-search config changes and pool utilization.",
        "CHG-2001",
    ),
    _incident(
        "INC-1008", "svc-auth", "Identity provider throttling auth-service",
        IncidentSeverity.P2, -28,
        "IdP is throttling auth-service JWKS requests; JWT caching looks off after the latest deploy.",
        "Find the auth deploy that changed JWT cache TTL.",
        "CHG-3001",
    ),
    _incident(
        "INC-1009", "svc-cart", "Cart merge duplicating items",
        IncidentSeverity.P3, -9,
        "Users see doubled cart items; the cart_merge_v2 flag was just enabled.",
        "Correlate feature-flag changes with cart deploys.",
        "CHG-4002",
    ),
    _incident(
        "INC-1010", "svc-notify", "Notify workers crashing on templates",
        IncidentSeverity.P2, -168,
        "notify-worker restarts spiking with null-pointer template errors; queue backing up.",
        "Check notify deploy history and worker restart metrics.",
        "CHG-5001",
    ),
]


def get_incident(incident_id: str) -> Dict[str, Any]:
    """
    Return the incident record (with ground truth) by id, or raise KeyError.

    Replay-suite variants (``INC-1001-s`` shifted, ``INC-1001-x`` scaled) resolve
    to their canonical base record — a permuted alert is still the same
    underlying incident, so the registry normalizes the suffix before lookup.
    """
    raw = str(incident_id)
    base_id = raw
    for suffix in ("-s", "-x"):
        if base_id.endswith(suffix):
            base_id = base_id[: -len(suffix)]
            break
    for rec in INCIDENTS:
        if rec["incident"].incident_id == base_id:
            return rec
    raise KeyError(f"Unknown incident: {incident_id}")


def list_incident_ids() -> List[str]:
    return [rec["incident"].incident_id for rec in INCIDENTS]


def logs_for(service: str, since: datetime | None = None) -> List[LogEntry]:
    entries = _LOGS.get(service, [])
    if since is None:
        return list(entries)
    return [e for e in entries if e.timestamp >= since]


def metrics_for(service: str, metric: str | None = None) -> List[MetricPoint]:
    entries = _METRICS.get(service, [])
    if metric is None:
        return list(entries)
    return [m for m in entries if m.metric == metric]


def changes_for(service: str) -> List[ChangeEvent]:
    return list(CHANGES.get(service, []))
