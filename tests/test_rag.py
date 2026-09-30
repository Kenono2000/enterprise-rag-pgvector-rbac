"""
tests/test_rag.py
-----------------
Automated tests for FastAPI endpoints in app/main.py.
"""

from unittest.mock import patch, AsyncMock
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_check():
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "healthy"


def test_query_unauthorized_when_require_google_true(monkeypatch):
    monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "true")
    response = client.post("/api/v1/query", json={"question": "What are Q3 results?"})
    assert response.status_code == 401
    assert "Authorization header with a Google ID token is required" in response.json()["detail"]


def test_query_with_legacy_header_when_require_google_false(monkeypatch):
    monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "false")
    with patch("app.main.generate_embedding", new_callable=AsyncMock) as mock_emb, \
         patch("app.main.DatabaseManager.secure_search", new_callable=AsyncMock) as mock_search, \
         patch("app.main.chat_completion", new_callable=AsyncMock) as mock_llm:

        mock_emb.return_value = [0.1] * 1536
        mock_search.return_value = [
            {
                "document_id": "doc1",
                "title": "Engineering Standards",
                "content": "Standard guidelines",
                "allowed_roles": ["engineer"],
                "similarity": 0.88,
            }
        ]
        mock_llm.return_value = "Follow the standards."

        response = client.post(
            "/api/v1/query",
            json={"question": "What are the standards?"},
            headers={"X-User-Roles": '["engineer"]'},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["answer"] == "Follow the standards."
        assert len(data["citations"]) == 1
        assert data["citations"][0]["document_id"] == "doc1"
        assert data["authorized_roles_evaluated"] == ["engineer"]


def test_query_with_verified_google_token(monkeypatch):
    monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "true")
    with patch("app.main.verify_google_token") as mock_verify, \
         patch("app.main.extract_roles") as mock_extract, \
         patch("app.main.generate_embedding", new_callable=AsyncMock) as mock_emb, \
         patch("app.main.DatabaseManager.secure_search", new_callable=AsyncMock) as mock_search, \
         patch("app.main.chat_completion", new_callable=AsyncMock) as mock_llm:

        mock_verify.return_value = {"sub": "google-user-123", "email": "alice@acme.com"}
        mock_extract.return_value = ["finance_executive"]
        mock_emb.return_value = [0.1] * 1536
        mock_search.return_value = [
            {
                "document_id": "audit-q3",
                "title": "Q3 Financial Audit",
                "content": "Margins were 24%",
                "allowed_roles": ["finance_executive"],
                "similarity": 0.95,
            }
        ]
        mock_llm.return_value = "Q3 margins were 24%."

        response = client.post(
            "/api/v1/query",
            json={"question": "What were the margins?"},
            headers={"Authorization": "Bearer fake.verified.token"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["answer"] == "Q3 margins were 24%."
        assert data["confidence_score"] == 0.95
        assert data["authorized_roles_evaluated"] == ["finance_executive"]
