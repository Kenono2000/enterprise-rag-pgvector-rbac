"""
tests/test_context_assembly.py
------------------------------
Unit tests for the Context Engineering pipeline (app/rag/context.py):
context assembly, deterministic prefix-cached prompt construction, and
token-bounded context compaction.
"""

import pytest

from app.rag.context import ContextAssemblyResult, ContextAssembler, assemble_context


def _chunk(title: str, content: str, chunk_index: int = 0, similarity: float = 0.9) -> dict:
    return {
        "document_id": f"doc-{title}",
        "title": title,
        "content": content,
        "chunk_index": chunk_index,
        "allowed_roles": ["engineer"],
        "similarity": similarity,
    }


def test_context_text_uses_citation_format():
    """Assembled context must use the canonical `[Doc: <Title>, Chunk <N>]` citation format."""
    result = ContextAssembler.assemble([_chunk("Policy", "Strict RBAC applies.")], "What is the policy?")

    assert isinstance(result, ContextAssemblyResult)
    assert "[Doc: Policy, Chunk 0]:\nStrict RBAC applies." in result.context_text
    assert result.context_tokens > 0
    assert result.citations_required is True


def test_assemble_small_context_not_compacted():
    """Contexts within the token budget must pass through without compaction."""
    chunks = [_chunk("Policy", "Strict RBAC applies.", similarity=0.95)]

    result = ContextAssembler.assemble(chunks, "What is the policy?", max_context_tokens=1000)

    assert result.compacted is False
    assert result.context_text == "[Doc: Policy, Chunk 0]:\nStrict RBAC applies."
    assert result.context_tokens <= 1000
    assert result.context_chunks == chunks
    assert result.citations_required is True


def test_assemble_empty_context_has_no_citations_required():
    """Empty authorized context must not demand citations and must stay token-free."""
    result = ContextAssembler.assemble([], "What is the policy?")

    assert result.context_text == ""
    assert result.compacted is False
    assert result.context_tokens == 0
    assert result.citations_required is False
    assert "AUTHORIZED CONTEXT" in result.prompt


def test_assemble_over_budget_compacts_to_highest_similarity():
    """Over-budget authorized context must be deterministically compacted to the highest-ranked chunks."""
    chunks = [
        _chunk("Doc B", "AAAAAAAAAA", chunk_index=0, similarity=0.50),
        _chunk("Doc A", "AAAAAAAAAA", chunk_index=0, similarity=0.90),
        _chunk("Doc C", "AAAAAAAAAA", chunk_index=0, similarity=0.70),
    ]

    result = ContextAssembler.assemble(chunks, "query", max_context_tokens=12)

    assert result.compacted is True
    # Budget of 12 tokens fits a single chunk (~9 tokens) but not two (~18 tokens).
    assert len(result.context_chunks) == 1
    assert result.context_chunks[0]["similarity"] == 0.90
    assert result.context_tokens <= 12


def test_assemble_prefix_hash_and_static_prefix_tokens_present():
    """The assembled prompt must expose a deterministic SHA-256 prefix hash and static-prefix token count."""
    result = ContextAssembler.assemble([_chunk("Policy", "Strict RBAC applies.")], "What is the policy?")

    assert len(result.prefix_hash) == 16
    assert result.static_prefix_tokens > 0
    assert result.prompt.startswith("You are an enterprise zero-trust AI assistant.")
    assert "Strict RBAC applies." in result.prompt


def test_assemble_deterministic_across_calls():
    """Repeated assembly of the same context must be deterministic (stable prefix hash + text)."""
    chunks = [_chunk("Policy", "Strict RBAC applies.", similarity=0.9)]
    first = ContextAssembler.assemble(chunks, "What is the policy?")
    second = ContextAssembler.assemble(chunks, "What is the policy?")

    assert first.context_text == second.context_text
    assert first.prefix_hash == second.prefix_hash
    assert first.prompt == second.prompt


def test_assemble_wrapper_matches_classmethod():
    """The module-level convenience wrapper must delegate to ContextAssembler.assemble."""
    chunks = [_chunk("Policy", "Strict RBAC applies.")]
    via_wrapper = assemble_context(chunks, "What is the policy?", max_context_tokens=500)
    via_class = ContextAssembler.assemble(chunks, "What is the policy?", max_context_tokens=500)

    assert via_wrapper.context_text == via_class.context_text
    assert via_wrapper.compacted == via_class.compacted
    assert via_wrapper.prompt == via_class.prompt


def test_context_assembly_result_rejects_extra_fields():
    """ContextAssemblyResult must enforce strict extra='forbid' schema discipline."""
    with pytest.raises(Exception):
        ContextAssemblyResult(
            context_chunks=[],
            context_text="",
            compacted=False,
            context_tokens=0,
            prefix_hash="deadbeefdeadbeef",
            static_prefix_tokens=10,
            prompt="prompt",
            citations_required=False,
            unexpected_field="boom",
        )
