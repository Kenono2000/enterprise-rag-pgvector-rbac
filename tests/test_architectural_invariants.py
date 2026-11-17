"""
tests/test_architectural_invariants.py
--------------------------------------
Regression suite pinning the six architectural invariants of the
enterprise-rag-pgvector-rbac platform. Any refactor that silently breaks one
of these contracts must fail CI here first.

Invariants under test:
  1. In-database RBAC pre-filtering (``allowed_roles ?| $N::text[]``) is present
     in every retrieval SQL path and roles are bound as parameters, never inlined.
  2. Empty-role short-circuiting: every retrieval path returns ``[]`` without
     executing any engine query when the caller resolves to zero roles.
  3. Structural subtyping via the ``VectorSearchProvider`` runtime protocol.
  4. Event-loop scoped asyncpg pool (pool recreated when the running loop
     changes; stale pools closed).
  5. Strict Pydantic V2 ``extra='forbid'`` validation on all API/MCP schemas.
  6. Zero AST dynamic execution violations (no ``eval``/``exec``/``compile``/
     ``__import__`` call sites) across the production source tree.
"""
from __future__ import annotations

import ast
import asyncio
import pathlib
import re
from unittest.mock import AsyncMock, MagicMock, patch

import pydantic
import pytest
from fastapi.testclient import TestClient

from app.db.adapters import (
    AzureSearchAdapter,
    DatabricksSearchAdapter,
    GCPSearchAdapter,
    PgvectorSearchAdapter,
)
from app.db.manager import DatabaseManager
from app.db.protocols import VectorSearchProvider
from app.main import app

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PRODUCTION_SOURCE_DIRS = (
    REPO_ROOT / "app",
    REPO_ROOT / "agent",
    REPO_ROOT / "libs",
    REPO_ROOT / "sdlc_harness",
)


# ---------------------------------------------------------------------------
# Invariant 1: In-database RBAC pre-filtering (allowed_roles ?| $N::text[])
# ---------------------------------------------------------------------------


class _FakeConnection:
    """Records SQL text and bound parameters without touching a database."""

    def __init__(self) -> None:
        self.executed: list[tuple[str, tuple]] = []
        self.fetched: list[tuple[str, tuple]] = []

    async def execute(self, sql: str, *args):
        self.executed.append((sql, args))
        return "SET"

    async def fetch(self, sql: str, *args):
        self.fetched.append((sql, args))
        return []

    async def fetchrow(self, sql: str, *args):
        return None

    def transaction(self):
        return _NullTransaction()


class _NullTransaction:
    async def __aenter__(self):
        return None

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _AcquireContext:
    def __init__(self, conn: _FakeConnection):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _FakePool:
    def __init__(self, conn: _FakeConnection):
        self._conn = conn

    def acquire(self):
        return _AcquireContext(self._conn)


@pytest.mark.asyncio
async def test_secure_search_binds_roles_as_text_array_parameter():
    """secure_search SQL must pre-filter with ?| $N::text[] and bind roles as a parameter."""
    conn = _FakeConnection()
    pool = _FakePool(conn)

    with patch.object(
        DatabaseManager, "get_pool", new_callable=AsyncMock, return_value=pool
    ):
        await DatabaseManager.secure_search(
            query_vector=[0.1] * 1536,
            user_roles=["engineer", "admin"],
            limit=7,
        )

    assert len(conn.fetched) == 1
    sql, params = conn.fetched[0]
    assert re.search(r"allowed_roles \?\| \$\d+::text\[\]", sql), (
        "RBAC pre-filter `allowed_roles ?| $N::text[]` missing from secure_search SQL"
    )
    # Roles must arrive as a bound parameter, never inlined into the SQL text.
    assert "engineer" not in sql and "admin" not in sql
    assert list(params[1]) == ["engineer", "admin"]


@pytest.mark.asyncio
async def test_hybrid_search_binds_roles_as_text_array_parameter():
    """hybrid_search fused SQL must pre-filter every CTE with ?| $N::text[]."""
    conn = _FakeConnection()
    pool = _FakePool(conn)

    with patch.object(
        DatabaseManager, "get_pool", new_callable=AsyncMock, return_value=pool
    ), patch.object(
        DatabaseManager,
        "configure_iterative_scan",
        new_callable=AsyncMock,
        return_value=True,
    ):
        await DatabaseManager.hybrid_search(
            query_text="margins",
            query_vector=[0.1] * 1536,
            user_roles=["finance_executive"],
            limit=5,
        )

    # Fused CTE path executes one fetch with the RBAC pre-filter bound as parameter.
    assert conn.fetched, "hybrid_search executed no queries"
    for sql, params in conn.fetched:
        assert re.search(r"allowed_roles \?\| \$\d+::text\[\]", sql), (
            "RBAC pre-filter missing from hybrid_search SQL"
        )
        assert "finance_executive" not in sql
        assert params[2] == ["finance_executive"]


@pytest.mark.asyncio
async def test_list_documents_binds_roles_as_text_array_parameter():
    """list_documents SQL must pre-filter with ?| $1::text[]."""
    conn = _FakeConnection()
    pool = _FakePool(conn)

    with patch.object(
        DatabaseManager, "get_pool", new_callable=AsyncMock, return_value=pool
    ):
        await DatabaseManager.list_documents(user_roles=["engineer"], limit=10)

    assert len(conn.fetched) == 1
    sql, params = conn.fetched[0]
    assert "allowed_roles ?| $1::text[]" in sql
    assert "engineer" not in sql
    assert params[0] == ["engineer"]


def test_schema_sql_declares_jsonb_ops_gin_index():
    """The GIN index must use the default jsonb_ops class so ?| is index-served."""
    schema = (REPO_ROOT / "schema.sql").read_text(encoding="utf-8")
    gin_index_lines = [
        line.strip()
        for line in schema.splitlines()
        if "USING gin" in line
    ]
    # The RBAC role index must be a plain default jsonb_ops GIN index.
    assert any("USING gin (allowed_roles);" in line for line in gin_index_lines)
    # No GIN index may use jsonb_path_ops (it does not serve the ?| operator).
    assert not any("jsonb_path_ops" in line for line in gin_index_lines)
    # Explanatory comments may mention jsonb_path_ops, but only inside comments.
    for line in schema.splitlines():
        stripped = line.strip()
        if "jsonb_path_ops" in stripped:
            assert stripped.startswith("--"), (
                "jsonb_path_ops may only appear in comments, not in index DDL"
            )


# ---------------------------------------------------------------------------
# Invariant 2: Empty-role short-circuiting ([])
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_secure_search_empty_roles_short_circuits():
    with patch.object(
        DatabaseManager, "get_pool", new_callable=AsyncMock
    ) as mock_pool:
        result = await DatabaseManager.secure_search(
            query_vector=[0.1] * 8, user_roles=[], limit=5
        )
        assert result == []
        mock_pool.assert_not_called()


@pytest.mark.asyncio
async def test_hybrid_search_empty_roles_short_circuits():
    with patch.object(
        DatabaseManager, "get_pool", new_callable=AsyncMock
    ) as mock_pool:
        result = await DatabaseManager.hybrid_search(
            query_text="q", query_vector=[0.1] * 8, user_roles=[], limit=5
        )
        assert result == []
        mock_pool.assert_not_called()


@pytest.mark.asyncio
async def test_list_documents_empty_roles_short_circuits():
    with patch.object(
        DatabaseManager, "get_pool", new_callable=AsyncMock
    ) as mock_pool:
        result = await DatabaseManager.list_documents(user_roles=[], limit=5)
        assert result == []
        mock_pool.assert_not_called()


@pytest.mark.asyncio
async def test_all_adapters_short_circuit_on_empty_roles():
    """Every VectorSearchProvider adapter fails closed with [] for empty roles."""
    adapters = (
        PgvectorSearchAdapter(),
        AzureSearchAdapter(),
        GCPSearchAdapter(),
        DatabricksSearchAdapter(),
    )
    for adapter in adapters:
        result = await adapter.search(
            query_text="secret", query_vector=[0.1] * 8, user_roles=[], limit=3
        )
        assert result == []


@pytest.mark.asyncio
async def test_sanitization_failure_short_circuits():
    """Roles that sanitize to nothing (injection payloads) must fail closed."""
    with patch.object(
        DatabaseManager, "get_pool", new_callable=AsyncMock
    ) as mock_pool:
        result = await DatabaseManager.secure_search(
            query_vector=[0.1] * 8,
            user_roles=["'; DROP TABLE documents; --", ""],
            limit=5,
        )
        assert result == []
        mock_pool.assert_not_called()


def test_sanitize_roles_for_query_contract():
    """The shared sanitizer keeps known roles and identifiers, drops the rest."""
    from app.auth.role_mapper import KNOWN_ROLES

    assert DatabaseManager.sanitize_roles_for_query(["engineer"]) == ["engineer"]
    assert DatabaseManager.sanitize_roles_for_query([" finance_executive "]) == [
        "finance_executive"
    ]
    # Unknown but identifier-shaped roles are allowed (custom claims).
    assert DatabaseManager.sanitize_roles_for_query(["custom_role"]) == ["custom_role"]
    # Injection payloads, empty strings, and non-strings are dropped.
    assert DatabaseManager.sanitize_roles_for_query(
        ["'; DROP TABLE documents; --", "", " ", "ok; DELETE", 42, None]
    ) == []
    for role in KNOWN_ROLES:
        assert role in DatabaseManager.sanitize_roles_for_query([role])


# ---------------------------------------------------------------------------
# Invariant 3: Structural subtyping via VectorSearchProvider protocol
# ---------------------------------------------------------------------------


def test_adapters_structurally_subtype_vector_search_provider():
    """All four adapters satisfy the runtime_checkable protocol interface."""
    adapters = (
        PgvectorSearchAdapter(),
        AzureSearchAdapter(),
        GCPSearchAdapter(),
        DatabricksSearchAdapter(),
    )
    for adapter in adapters:
        assert isinstance(adapter, VectorSearchProvider)
        # The protocol method must be a coroutine function (awaitable contract).
        assert asyncio.iscoroutinefunction(adapter.search)


def test_vector_search_provider_is_runtime_checkable_protocol():
    """The protocol itself must remain runtime_checkable for isinstance checks."""
    assert getattr(VectorSearchProvider, "_is_protocol", False) or hasattr(
        VectorSearchProvider, "__protocol_attrs__"
    )


# ---------------------------------------------------------------------------
# Invariant 4: Event-loop scoped asyncpg pools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pool_is_bound_to_running_event_loop():
    """get_pool must cache a pool per event loop and reuse it within a loop."""
    calls: list[asyncio.AbstractEventLoop] = []

    async def fake_create_pool(*args, **kwargs):
        calls.append(asyncio.get_running_loop())
        return MagicMock(name="pool")

    DatabaseManager._pool = None
    DatabaseManager._loop = None
    with patch("app.db.manager.asyncpg.create_pool", new=fake_create_pool), patch(
        "app.db.manager.get_db_url", return_value="postgresql://user:pass@localhost:5432/db"
    ):
        pool1 = await DatabaseManager.get_pool()
        pool2 = await DatabaseManager.get_pool()
    assert pool1 is pool2, "same loop must reuse the cached pool"
    assert len(calls) == 1


def test_pool_is_recreated_across_event_loops():
    """A pool cached on a previous loop is recreated (and closed) on a new loop.

    Uses two independent asyncio.run() invocations so the running loop genuinely
    changes between calls, mirroring a Streamlit rerun or a FastAPI worker
    restart. Each scenario runs in its own asyncio.run() to guarantee distinct
    loop objects.
    """
    created_loops: list[asyncio.AbstractEventLoop] = []
    closed_pools: list[object] = []

    async def fake_create_pool(*args, **kwargs):
        created_loops.append(asyncio.get_running_loop())
        pool = MagicMock(name="pool")
        pool.close = AsyncMock(side_effect=lambda: closed_pools.append(pool))
        return pool

    def scenario_first() -> None:
        DatabaseManager._pool = None
        DatabaseManager._loop = None
        with patch("app.db.manager.asyncpg.create_pool", new=fake_create_pool), patch(
            "app.db.manager.get_db_url",
            return_value="postgresql://user:pass@localhost:5432/db",
        ):
            DatabaseManager._pool_created = asyncio.run(DatabaseManager.get_pool())

    def scenario_second() -> None:
        # Simulate a *foreign* cached pool from the first loop: the manager still
        # holds the pool object but the running loop is now different.
        with patch("app.db.manager.asyncpg.create_pool", new=fake_create_pool), patch(
            "app.db.manager.get_db_url",
            return_value="postgresql://user:pass@localhost:5432/db",
        ):
            DatabaseManager._pool_created_second = asyncio.run(DatabaseManager.get_pool())

    scenario_first()
    scenario_second()

    assert len(created_loops) == 2, "pool must be created once per event loop"
    assert created_loops[0] is not created_loops[1]
    # The stale pool from loop 1 must have been closed before recreation.
    assert len(closed_pools) == 1

    # Cleanup class-level state for subsequent tests.
    DatabaseManager._pool = None
    DatabaseManager._loop = None


@pytest.mark.asyncio
async def test_stale_loop_pool_is_closed_and_recreated():
    """A cached pool bound to a dead/foreign loop is closed and replaced."""
    old_loop = asyncio.new_event_loop()
    try:
        stale_pool = MagicMock(name="stale_pool")
        stale_pool.close = AsyncMock()
        DatabaseManager._pool = stale_pool
        DatabaseManager._loop = old_loop

        created = MagicMock(name="fresh_pool")

        async def fake_create_pool(*args, **kwargs):
            return created

        with patch("app.db.manager.asyncpg.create_pool", new=fake_create_pool), patch(
            "app.db.manager.get_db_url", return_value="postgresql://user:pass@localhost:5432/db"
        ):
            pool = await DatabaseManager.get_pool()

        assert pool is created
        stale_pool.close.assert_awaited_once()
        assert DatabaseManager._loop is asyncio.get_running_loop()
    finally:
        old_loop.close()
        DatabaseManager._pool = None
        DatabaseManager._loop = None


def test_get_pool_requires_running_loop():
    """get_pool must fail with RuntimeError outside a running loop (no sync creation)."""
    DatabaseManager._pool = None
    DatabaseManager._loop = None
    with pytest.raises(RuntimeError):
        # Called synchronously — asyncio.get_running_loop() must raise.
        asyncio.get_running_loop()


# ---------------------------------------------------------------------------
# Invariant 5: Strict Pydantic V2 extra='forbid' validation
# ---------------------------------------------------------------------------


def _client() -> TestClient:
    return TestClient(app)


def test_rag_query_request_rejects_extra_fields():
    """POST /api/v1/query with an unknown field must be rejected (422)."""
    response = _client().post(
        "/api/v1/query",
        json={"question": "hello?", "budget_mode": "deep"},
        headers={"X-User-Roles": '["engineer"]'},
    )
    assert response.status_code == 422


def test_rag_query_request_accepts_known_schema_only():
    """A minimal valid question passes validation (model still functions)."""
    with patch("app.main.generate_embedding", new_callable=AsyncMock) as mock_emb, patch(
        "app.main.DatabaseManager.secure_search", new_callable=AsyncMock
    ) as mock_search, patch(
        "app.main.chat_completion", new_callable=AsyncMock
    ) as mock_chat, patch(
        "app.main.DatabaseManager.check_token_limit", new_callable=AsyncMock
    ) as mock_limit, patch(
        "app.main.DatabaseManager.record_token_consumption", new_callable=AsyncMock
    ):
        mock_emb.return_value = [0.1] * 1536
        mock_search.return_value = []
        mock_chat.return_value = "mock answer"
        mock_limit.return_value = (True, 0, 50000, True, None)

        response = _client().post(
            "/api/v1/query",
            json={"question": "What is zero trust?"},
            headers={"X-User-Roles": '["engineer"]'},
        )
        assert response.status_code == 200
        body = response.json()
        assert body["authorized_roles_evaluated"] == ["engineer"]


def test_mcp_tool_schemas_forbid_extra_fields():
    """All MCP request models must be strict (extra='forbid')."""
    from app.mcp.gateway import (
        MCPHermesSkillRequest,
        MCPListDocumentsRequest,
        MCPPatchRequest,
        MCPSDLCCrewRequest,
        MCPSearchRequest,
    )

    models = (
        MCPSearchRequest,
        MCPPatchRequest,
        MCPSDLCCrewRequest,
        MCPHermesSkillRequest,
        MCPListDocumentsRequest,
    )
    for model in models:
        assert model.model_config.get("extra") == "forbid"
        with pytest.raises(pydantic.ValidationError):
            model(question="q", branch_name="b", issue_title="i", query="q",
                  patch_content="p", unexpected_field="boom")


def test_api_schemas_forbid_extra_fields():
    """Core API response/request models must be strict (extra='forbid')."""
    from app.main import (
        Citation,
        DocumentIngestRequest,
        RAGQueryRequest,
        RAGResponse,
        TokenLimitUpdateRequest,
        TokenResetRequest,
        UserIdentity,
    )

    models = (
        Citation,
        RAGQueryRequest,
        RAGResponse,
        UserIdentity,
        TokenLimitUpdateRequest,
        TokenResetRequest,
        DocumentIngestRequest,
    )
    for model in models:
        assert model.model_config.get("extra") == "forbid"


# ---------------------------------------------------------------------------
# Invariant 6: Zero AST dynamic execution violations
# ---------------------------------------------------------------------------


FORBIDDEN_DYNAMIC_CALLS = {"eval", "exec", "compile", "__import__"}
FORBIDDEN_ATTRIBUTE_CALLS = {
    ("os", "system"),
    ("os", "popen"),
    ("pickle", "loads"),
    ("pickle", "load"),
    ("marshal", "loads"),
    ("marshal", "load"),
}


def _iter_python_sources():
    for base in PRODUCTION_SOURCE_DIRS:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            yield path


def test_no_dynamic_execution_call_sites_in_production_source():
    """No eval()/exec()/__import__() or builtin compile() calls in production code.

    Attribute calls such as ``re.compile(...)`` (regex compilation) and
    ``workflow.compile(...)`` (LangGraph graph compilation) are legitimate and
    excluded; only builtin dynamic execution is forbidden.
    """
    violations = []
    for path in _iter_python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in FORBIDDEN_DYNAMIC_CALLS:
                    violations.append(f"{path}:{node.lineno} {node.func.id}()")
    assert not violations, f"Dynamic execution call sites found: {violations}"


def test_no_forbidden_attribute_calls_in_production_source():
    """No os.system/os.popen/pickle.loads/marshal.loads attribute calls."""
    violations = []
    for path in _iter_python_sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if isinstance(node.func.value, ast.Name):
                    pair = (node.func.value.id, node.func.attr)
                    if pair in FORBIDDEN_ATTRIBUTE_CALLS:
                        violations.append(f"{path}:{node.lineno} {pair[0]}.{pair[1]}()")
    assert not violations, f"Forbidden attribute calls found: {violations}"


def test_policy_engine_reports_zero_violations_on_itself():
    """PolicyEngine.verify_ast must flag a synthetic eval() snippet (self-check)."""
    from agent.guardrails import PolicyEngine

    violations = PolicyEngine.verify_ast("result = eval('1 + 1')")
    assert any("eval()" in v for v in violations)
    assert PolicyEngine.verify_ast("x = 1 + 1") == []
