"""
tests/test_security_rbac.py
---------------------------
Security and RBAC verification test suite.
Validates SQL injection resilience, parameterization, and zero-trust role filtering.
"""

from unittest.mock import AsyncMock, patch, MagicMock
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.db.manager import DatabaseManager
from app.auth.role_mapper import KNOWN_ROLES

client = TestClient(app)


@pytest.mark.asyncio
async def test_database_manager_zero_trust_empty_roles():
    """Verify that an empty role list short-circuits immediately without running queries."""
    with patch.object(DatabaseManager, "get_pool", new_callable=AsyncMock) as mock_pool:
        results = await DatabaseManager.secure_search(
            query_vector=[0.1] * 1536,
            user_roles=[],
            limit=5,
        )
        assert results == []
        mock_pool.assert_not_called()


@pytest.mark.asyncio
async def test_database_manager_sanitizes_sql_injection_roles():
    """Verify that malicious injection roles are filtered out and rejected."""
    injection_roles = [
        "'; DROP TABLE enterprise_documents; --",
        "' OR '1'='1",
        "admin\" OR 1=1 --",
    ]
    with patch.object(DatabaseManager, "get_pool", new_callable=AsyncMock) as mock_pool:
        results = await DatabaseManager.secure_search(
            query_vector=[0.1] * 1536,
            user_roles=injection_roles,
            limit=5,
        )
        assert results == []
        mock_pool.assert_not_called()


@pytest.mark.asyncio
async def test_database_manager_parameterized_query_execution():
    """Verify that safe roles are passed as bound parameters ($2::text[]) and not concatenated."""
    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = [
        {"document_id": "doc1", "title": "Eng Doc", "content": "hello", "similarity": 0.9}
    ]
    mock_pool = MagicMock()
    
    class MockAcquireContext:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, exc_type, exc, tb):
            pass

    mock_pool.acquire.return_value = MockAcquireContext()

    with patch.object(DatabaseManager, "get_pool", new_callable=AsyncMock, return_value=mock_pool):
        results = await DatabaseManager.secure_search(
            query_vector=[0.0] * 1536,
            user_roles=["engineer"],
            limit=3,
        )
        assert len(results) == 1
        assert mock_conn.fetch.called
        
        args = mock_conn.fetch.call_args[0]
        sql_query = args[0]
        # Verify parameterized placeholders
        assert "$1::vector" in sql_query
        assert "$2::text[]" in sql_query
        assert "$3" in sql_query
        # Ensure raw role string is not inlined in SQL
        assert "'engineer'" not in sql_query
        # Ensure user_roles are passed in parameter 2
        assert args[2] == ["engineer"]
        assert args[3] == 3


def test_api_rejects_malformed_x_user_roles(monkeypatch):
    """Verify API returns 400 Bad Request for non-array X-User-Roles."""
    monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "false")
    response = client.post(
        "/api/v1/query",
        json={"question": "Test question?"},
        headers={"X-User-Roles": '"single_string_not_list"'},
    )
    assert response.status_code == 400
    assert "Invalid X-User-Roles header format" in response.json()["detail"]


def test_api_filters_sql_injection_in_headers(monkeypatch):
    """Verify malicious SQL injection in header roles gets sanitized and returns no unauthorized docs."""
    monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "false")
    with patch("app.main.generate_embedding", new_callable=AsyncMock) as mock_emb, \
         patch("app.main.DatabaseManager.secure_search", new_callable=AsyncMock) as mock_search:

        mock_emb.return_value = [0.1] * 1536
        mock_search.return_value = []

        response = client.post(
            "/api/v1/query",
            json={"question": "Confidential data?"},
            headers={"X-User-Roles": '["\' OR \'1\'=\'1", "admin\'; DROP TABLE users; --"]'},
        )
        assert response.status_code == 200
        data = response.json()
        # All malicious roles were filtered out
        assert data["authorized_roles_evaluated"] == []
        assert data["citations"] == []
        assert "No authorized documentation found" in data["answer"]
