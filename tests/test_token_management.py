"""
tests/test_token_management.py
------------------------------
Unit and integration tests for PostgreSQL-backed token consumption tracking,
token ledger auditing, and managed limit enforcement with administrative turn-off controls.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest
from fastapi.testclient import TestClient

from app.main import app, api_token_breaker
from app.db.manager import DatabaseManager
from agent.guardrails import TokenCircuitBreaker

client = TestClient(app)


# ---------------------------------------------------------------------------
# In-Memory TokenCircuitBreaker Unit Tests
# ---------------------------------------------------------------------------

def test_circuit_breaker_enforce_limit_toggle():
    """Verify option to turn off limit enforcement (enforce_limit=False)."""
    breaker = TokenCircuitBreaker(max_tokens_per_request=500, max_tokens_per_issue=200, enforce_limit=True)
    caller = "test-user-1"

    # Consumes 150 tokens - within limit
    allowed, rem, err = breaker.check_and_consume(caller, 150)
    assert allowed is True
    assert rem == 50
    assert err is None

    # Next 100 tokens trips breaker because 150 + 100 > 200
    allowed, rem, err = breaker.check_and_consume(caller, 100)
    assert allowed is False
    assert "exceed max_tokens_per_issue" in err
    assert breaker.is_blocked(caller) is True

    # Now turn off limit enforcement for this caller
    breaker.set_enforce_limit(caller, enforce=False)
    breaker.set_blocked(caller, blocked=False)
    allowed, rem, err = breaker.check_and_consume(caller, 50)
    assert allowed is True
    assert err is None


def test_circuit_breaker_kill_switch_turn_off():
    """Verify manual kill switch immediately turns off token consumption."""
    breaker = TokenCircuitBreaker(max_tokens_per_request=1000, max_tokens_per_issue=5000)
    caller = "test-user-killswitch"

    # Initially allowed
    allowed, rem, err = breaker.check_and_consume(caller, 100)
    assert allowed is True

    # Turn off token consumption
    breaker.set_blocked(caller, True)
    assert breaker.is_blocked(caller) is True

    # Subsequent consumption blocked immediately
    allowed, rem, err = breaker.check_and_consume(caller, 50)
    assert allowed is False
    assert "Token consumption turned off" in err

    # Reset unblocks caller
    breaker.reset(caller)
    assert breaker.is_blocked(caller) is False
    assert breaker.get_usage(caller) == 0


# ---------------------------------------------------------------------------
# DatabaseManager Token Methods Tests (Mocked asyncpg Pool)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_db_record_token_consumption():
    """Verify token consumption persists to ledger and updates managed limits."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()

    class MockTransaction:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            pass

    mock_conn.transaction = MagicMock(return_value=MockTransaction())

    # Mock fetchrow for ledger insert and limit upsert
    mock_conn.fetchrow.side_effect = [
        {"id": "a0000000-0000-0000-0000-000000000001", "caller_id": "eng@corp.com", "total_tokens": 120, "created_at": "2026-10-30T12:00:00Z"},
        {"caller_id": "eng@corp.com", "max_budget_tokens": 50000, "current_tokens": 120, "enforce_limit": True, "is_blocked": False},
    ]

    mock_acquire = AsyncMock()
    mock_acquire.__aenter__.return_value = mock_conn
    mock_acquire.__aexit__.return_value = None
    mock_pool.acquire.return_value = mock_acquire

    with patch.object(DatabaseManager, "get_pool", return_value=mock_pool):
        result = await DatabaseManager.record_token_consumption(
            caller_id="eng@corp.com",
            prompt_tokens=80,
            completion_tokens=40,
            model="gpt-4o",
            operation_type="rag_query",
        )
        assert result["total_tokens_consumed"] == 120
        assert result["cumulative_tokens"] == 120
        assert result["is_blocked"] is False
        assert result["enforce_limit"] is True


@pytest.mark.asyncio
async def test_db_check_token_limit_allowed_and_blocked():
    """Verify check_token_limit enforces limits and honors blocked killswitch."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()

    # Case 1: Caller under limit
    mock_conn.fetchrow.return_value = {
        "caller_id": "user1@corp.com",
        "max_budget_tokens": 10000,
        "current_tokens": 4000,
        "enforce_limit": True,
        "is_blocked": False,
    }
    mock_acquire = AsyncMock()
    mock_acquire.__aenter__.return_value = mock_conn
    mock_acquire.__aexit__.return_value = None
    mock_pool.acquire.return_value = mock_acquire

    with patch.object(DatabaseManager, "get_pool", return_value=mock_pool):
        allowed, cur, max_b, enforce, err = await DatabaseManager.check_token_limit("user1@corp.com", 500)
        assert allowed is True
        assert cur == 4000
        assert max_b == 10000
        assert err is None

        # Case 2: Caller exceeded limit with enforce_limit=True
        mock_conn.fetchrow.return_value = {
            "caller_id": "user1@corp.com",
            "max_budget_tokens": 10000,
            "current_tokens": 9800,
            "enforce_limit": True,
            "is_blocked": False,
        }
        allowed, cur, max_b, enforce, err = await DatabaseManager.check_token_limit("user1@corp.com", 300)
        assert allowed is False
        assert "Token managed limit reached" in err

        # Case 3: Caller exceeded limit BUT enforce_limit=False (option to turn off limit)
        mock_conn.fetchrow.return_value = {
            "caller_id": "user1@corp.com",
            "max_budget_tokens": 10000,
            "current_tokens": 12000,
            "enforce_limit": False,
            "is_blocked": False,
        }
        allowed, cur, max_b, enforce, err = await DatabaseManager.check_token_limit("user1@corp.com", 300)
        assert allowed is True
        assert enforce is False
        assert err is None

        # Case 4: Caller kill-switch active (is_blocked=True)
        mock_conn.fetchrow.return_value = {
            "caller_id": "user1@corp.com",
            "max_budget_tokens": 10000,
            "current_tokens": 1000,
            "enforce_limit": True,
            "is_blocked": True,
        }
        allowed, cur, max_b, enforce, err = await DatabaseManager.check_token_limit("user1@corp.com", 50)
        assert allowed is False
        assert "Token consumption turned off" in err


@pytest.mark.asyncio
async def test_db_set_managed_limit_and_reset():
    """Verify setting limits, toggling enforcement/blocked, and resetting usage."""
    mock_pool = MagicMock()
    mock_conn = AsyncMock()

    mock_conn.fetchrow.side_effect = [
        {"caller_id": "user1@corp.com", "max_budget_tokens": 50000, "current_tokens": 1000, "enforce_limit": True, "is_blocked": False},
        {"caller_id": "user1@corp.com", "max_budget_tokens": 75000, "current_tokens": 1000, "enforce_limit": False, "is_blocked": False},
    ]
    mock_conn.execute.return_value = "UPDATE 1"

    mock_acquire = AsyncMock()
    mock_acquire.__aenter__.return_value = mock_conn
    mock_acquire.__aexit__.return_value = None
    mock_pool.acquire.return_value = mock_acquire

    with patch.object(DatabaseManager, "get_pool", return_value=mock_pool):
        updated = await DatabaseManager.set_token_managed_limit(
            caller_id="user1@corp.com",
            max_budget_tokens=75000,
            enforce_limit=False,
        )
        assert updated["max_budget_tokens"] == 75000
        assert updated["enforce_limit"] is False

        reset_ok = await DatabaseManager.reset_token_usage("user1@corp.com")
        assert reset_ok is True


# ---------------------------------------------------------------------------
# FastAPI Endpoints Tests
# ---------------------------------------------------------------------------

def test_api_token_usage_endpoint(monkeypatch):
    """Test GET /api/v1/tokens/usage returns quota and usage metrics."""
    monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "false")
    with patch.object(DatabaseManager, "get_token_managed_limits", new_callable=AsyncMock) as mock_limits:
        mock_limits.return_value = [
            {
                "caller_id": "dev-user",
                "max_budget_tokens": 50000,
                "current_tokens": 1250,
                "enforce_limit": True,
                "is_blocked": False,
                "tier": "enterprise",
            }
        ]
        resp = client.get("/api/v1/tokens/usage?caller_id=dev-user", headers={"X-User-Roles": '["engineer"]'})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["caller_id"] == "dev-user"
        assert data[0]["current_tokens"] == 1250
        assert data[0]["remaining_tokens"] == 48750
        assert data[0]["enforce_limit"] is True


def test_api_token_limit_configure_and_turn_off(monkeypatch):
    """Test POST /api/v1/tokens/limit to turn off enforcement or turn off consumption."""
    monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "false")
    with patch.object(DatabaseManager, "set_token_managed_limit", new_callable=AsyncMock) as mock_set:
        mock_set.return_value = {
            "caller_id": "dev-user",
            "max_budget_tokens": 30000,
            "current_tokens": 500,
            "enforce_limit": False,
            "is_blocked": True,
        }
        resp = client.post(
            "/api/v1/tokens/limit",
            json={"caller_id": "dev-user", "max_budget_tokens": 30000, "enforce_limit": False, "is_blocked": True},
            headers={"X-User-Roles": '["admin"]'},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "success"
        assert data["limit"]["is_blocked"] is True
        assert data["limit"]["enforce_limit"] is False


def test_api_token_reset_endpoint(monkeypatch):
    """Test POST /api/v1/tokens/reset resets caller tokens."""
    monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "false")
    with patch.object(DatabaseManager, "reset_token_usage", new_callable=AsyncMock) as mock_reset:
        mock_reset.return_value = True
        resp = client.post(
            "/api/v1/tokens/reset",
            json={"caller_id": "dev-user"},
            headers={"X-User-Roles": '["engineer"]'},
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"
        assert resp.json()["reset_db"] is True


def test_query_blocked_when_token_consumption_turned_off(monkeypatch):
    """Test /api/v1/query returns HTTP 429 when token consumption is turned off."""
    monkeypatch.setenv("REQUIRE_GOOGLE_AUTH", "false")
    with patch.object(DatabaseManager, "check_token_limit", new_callable=AsyncMock) as mock_chk:
        mock_chk.return_value = (
            False,
            50000,
            50000,
            True,
            "Token managed limit reached: 50000 exceeds managed limit of 50000. Token consumption turned off.",
        )
        resp = client.post(
            "/api/v1/query",
            json={"question": "What is zero-trust vector RBAC?"},
            headers={"X-User-Roles": '["engineer"]'},
        )
        assert resp.status_code == 429
        assert "Token managed limit reached" in resp.json()["detail"]
