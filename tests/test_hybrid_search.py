"""
tests/test_hybrid_search.py
---------------------------
Unit and integration tests for Hybrid Search (Dense Vector + Sparse Full-Text RRF),
cross-encoder candidate re-ranking, and GroundingGuardrail anti-hallucination checks.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.db.manager import DatabaseManager
from libs.utilities import rerank_candidates
from agent.guardrails import GroundingGuardrail


@pytest.mark.asyncio
async def test_database_manager_hybrid_search_rrf_fusion():
    """Verify hybrid_search combines dense and sparse search via Reciprocal Rank Fusion."""
    mock_conn = AsyncMock()

    # Mock dense search rows (HNSW vector similarity)
    dense_results = [
        {
            "chunk_id_pk": "chunk-1-uuid",
            "document_id": "FIN-2026-001",
            "title": "Executive Q3 Financial Audit",
            "chunk_index": 0,
            "content": "Operating margins in Q3 increased by 14.2%.",
            "allowed_roles": ["finance_executive"],
            "similarity": 0.95,
        },
        {
            "chunk_id_pk": "chunk-2-uuid",
            "document_id": "ENG-2026-105",
            "title": "Public Engineering Guidelines",
            "chunk_index": 0,
            "content": "All backend microservices must implement asynchronous I/O.",
            "allowed_roles": ["engineer"],
            "similarity": 0.82,
        },
    ]

    # Mock sparse search rows (GIN full-text search)
    sparse_results = [
        {
            "chunk_id_pk": "chunk-1-uuid",
            "document_id": "FIN-2026-001",
            "title": "Executive Q3 Financial Audit",
            "chunk_index": 0,
            "content": "Operating margins in Q3 increased by 14.2%.",
            "allowed_roles": ["finance_executive"],
            "text_rank": 0.75,
            "similarity": 0.95,
        },
    ]

    mock_conn.fetch.side_effect = [dense_results, sparse_results]

    class MockPoolAcquire:
        async def __aenter__(self):
            return mock_conn
        async def __aexit__(self, exc_type, exc, tb):
            pass

    mock_pool = MagicMock()
    mock_pool.acquire.return_value = MockPoolAcquire()

    with patch.object(DatabaseManager, "get_pool", new_callable=AsyncMock, return_value=mock_pool):
        results = await DatabaseManager.hybrid_search(
            query_text="operating margins Q3",
            query_vector=[0.1] * 1536,
            user_roles=["finance_executive"],
            limit=2,
            rrf_k=60,
        )

        assert len(results) == 2
        # chunk-1 appeared in both dense and sparse, so its RRF score must be highest
        top = results[0]
        assert top["document_id"] == "FIN-2026-001"
        assert top["dense_rank"] == 1
        assert top["sparse_rank"] == 1
        # RRF formula: 1/(60+1) + 1/(60+1) = 2/61 ~ 0.03278
        expected_score = (1.0 / 61) + (1.0 / 61)
        assert pytest.approx(top["rrf_score"], rel=1e-3) == expected_score


@pytest.mark.asyncio
async def test_database_manager_hybrid_search_zero_trust_empty_roles():
    """Verify hybrid_search returns empty list immediately if caller has no roles."""
    res = await DatabaseManager.hybrid_search(
        query_text="finance margins",
        query_vector=[0.1] * 1536,
        user_roles=[],
    )
    assert res == []


def test_rerank_candidates_deterministic_fallback():
    """Verify rerank_candidates scores candidates combining similarity, query term overlap, and RRF."""
    candidates = [
        {
            "document_id": "doc-low",
            "title": "General Topic",
            "content": "Nothing relevant here at all.",
            "similarity": 0.60,
            "rrf_score": 0.01,
        },
        {
            "document_id": "doc-high",
            "title": "Exact Architecture",
            "content": "Detailed microservices architecture and zero-trust authentication guidelines.",
            "similarity": 0.90,
            "rrf_score": 0.03,
        },
    ]

    reranked = rerank_candidates("microservices architecture", candidates, top_k=2)
    assert len(reranked) == 2
    assert reranked[0]["document_id"] == "doc-high"
    assert "rerank_score" in reranked[0]
    assert reranked[0]["rerank_score"] > reranked[1]["rerank_score"]


def test_grounding_guardrail_valid_citation():
    """Verify GroundingGuardrail accepts answers with exact [Doc: <Title>, Chunk <Index>] citations."""
    context = [{"title": "Q3 Financial Audit", "chunk_index": 0}]
    answer = "Operating margins increased by 14.2% [Doc: Q3 Financial Audit, Chunk 0]."

    eval_result = GroundingGuardrail.validate_response(answer, context)
    assert eval_result["grounded"] is True
    assert eval_result["violations"] == []
    assert len(eval_result["citations_found"]) == 1


def test_grounding_guardrail_explicit_unknown_admission():
    """Verify GroundingGuardrail accepts explicit admission when information is missing."""
    context = []
    answer = "I do not have sufficient information in the authorized documents to answer this question."

    eval_result = GroundingGuardrail.validate_response(answer, context)
    assert eval_result["grounded"] is True
    assert eval_result["admitted_unknown"] is True
    assert eval_result["violations"] == []


def test_grounding_guardrail_flags_unsupported_citation():
    """Verify GroundingGuardrail flags citations for documents absent from context."""
    context = [{"title": "Public Engineering Guidelines"}]
    answer = "Executive bonuses were doubled [Doc: Unrelated Leak, Chunk 1]."

    eval_result = GroundingGuardrail.validate_response(answer, context)
    assert eval_result["grounded"] is False
    assert any("not found in authorized context" in v for v in eval_result["violations"])
