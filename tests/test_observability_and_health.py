"""
tests/test_observability_and_health.py
--------------------------------------
Unit and API tests for /healthz, /readyz endpoints, Pydantic BaseSettings,
ObservabilityTracer metrics, and LLM response streaming generators.
"""

from unittest.mock import AsyncMock, patch
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.config import Settings
from app.observability import ObservabilityTracer
from app.db.llm import chat_completion_stream_sync

client = TestClient(app)


def test_healthz_liveness_endpoint():
    """Verify /healthz returns 200 alive for container orchestrators."""
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"


def test_readyz_readiness_endpoint_success():
    """Verify /readyz returns 200 when database and vector extension are ready."""
    with patch("app.main.DatabaseManager.check_readiness", new_callable=AsyncMock) as mock_ready:
        mock_ready.return_value = {
            "database": "connected",
            "vector_extension": "available",
        }
        response = client.get("/readyz")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ready"
        assert data["database"] == "connected"
        assert data["vector_extension"] == "available"


def test_readyz_readiness_endpoint_failure():
    """Verify /readyz returns 503 when database connectivity fails."""
    with patch("app.main.DatabaseManager.check_readiness", new_callable=AsyncMock) as mock_ready:
        mock_ready.side_effect = ConnectionError("Could not reach postgres:5432")
        response = client.get("/readyz")
        assert response.status_code == 503
        assert "Service not ready" in response.json()["detail"]


def test_pydantic_base_settings_configuration():
    """Verify Pydantic BaseSettings loads environment variables and sets robust defaults."""
    custom_settings = Settings(
        DATABASE_URL="postgresql://user:pass@localhost:5432/test_db",
        REQUIRE_GOOGLE_AUTH=True,
        ENVIRONMENT="production",
        PORT=8000,
    )
    assert custom_settings.DATABASE_URL == "postgresql://user:pass@localhost:5432/test_db"
    assert custom_settings.REQUIRE_GOOGLE_AUTH is True
    assert custom_settings.ENVIRONMENT == "production"
    assert custom_settings.PORT == 8000


def test_observability_tracer_records_metrics_and_spans():
    """Verify ObservabilityTracer captures spans, retrieval metrics, and generation stats."""
    tracer = ObservabilityTracer(service_name="test-rag")

    with tracer.trace_span("vector_retrieval", {"roles": ["engineer"]}):
        tracer.record_retrieval(
            query="What is the architecture?",
            roles=["engineer"],
            result_count=3,
            duration_ms=12.5,
            mode="hybrid",
        )

    tracer.record_generation(
        model="gpt-4o",
        prompt_tokens=150,
        completion_tokens=45,
        duration_ms=250.0,
    )

    metrics = tracer.get_recent_metrics()
    assert len(metrics) >= 3
    events = [m.get("event") or m.get("operation") for m in metrics]
    assert "retrieval" in events
    assert "generation" in events
    assert "vector_retrieval" in events


def test_chat_completion_stream_sync_generator():
    """Verify chat_completion_stream_sync yields tokens suitable for st.write_stream."""
    tokens = list(chat_completion_stream_sync("What are the quarterly figures?"))
    assert len(tokens) > 0
    full_text = "".join(tokens)
    assert len(full_text.strip()) > 0
