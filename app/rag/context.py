"""
app/rag/context.py
------------------
Context Engineering pipeline for the Zero-Trust Enterprise RAG platform.

Implements the "Context Engineering" discipline — the successor to ad-hoc prompt
templating — as a deterministic, testable pipeline:

    1. ASSEMBLE  — convert authorized retrieval chunks into grounded context text.
    2. CACHE     — build a deterministic static-prefix prompt whose SHA-256 prefix hash
                  enables cross-turn KV prefix-cache hits on OpenAI / Gemini.
    3. COMPACT   — token-bound context compaction when the authorized context exceeds
                  the per-request context budget, keeping the highest-similarity chunks.

All steps are deterministic and offline-testable; no network or LLM calls are made.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict

from agent.guardrails import GroundingGuardrail, TokenCircuitBreaker


class ContextAssemblyResult(BaseModel):
    """Deterministic outcome of context assembly for a single RAG turn."""

    model_config = ConfigDict(extra="forbid")

    context_chunks: List[Dict[str, Any]]
    context_text: str
    compacted: bool
    context_tokens: int
    prefix_hash: str
    static_prefix_tokens: int
    prompt: str
    citations_required: bool


class ContextAssembler:
    """Deterministic context assembly, token-bounded compaction, and prefix-cached prompt builder."""

    DEFAULT_MAX_CONTEXT_TOKENS: int = 4000

    # ------------------------------------------------------------------
    # Step 1 — Assemble
    # ------------------------------------------------------------------
    @classmethod
    def chunk_to_line(cls, chunk: Optional[Dict[str, Any]]) -> str:
        if not chunk:
            return ""
        title = str(chunk.get("title") or chunk.get("document_id") or "Document")
        chunk_index = int(chunk.get("chunk_index") or 0)
        content = str(chunk.get("content") or chunk.get("text") or "")
        return f"[Doc: {title}, Chunk {chunk_index}]:\n{content}"

    @classmethod
    def assemble_context_text(cls, context_chunks: Optional[List[Dict[str, Any]]]) -> str:
        lines = [cls.chunk_to_line(c) for c in (context_chunks or []) if c]
        return "\n\n".join(line for line in lines if line)

    # ------------------------------------------------------------------
    # Step 3 — Compact (deterministic, similarity-ranked, token-bounded)
    # ------------------------------------------------------------------
    @classmethod
    def _compact(cls, context_chunks: List[Dict[str, Any]], max_context_tokens: int) -> List[Dict[str, Any]]:
        kept: List[Dict[str, Any]] = []
        accumulated = ""
        budget = max(1, int(max_context_tokens))
        ordered = sorted(
            (c for c in context_chunks if c),
            key=lambda c: float(c.get("similarity") or 0.0),
            reverse=True,
        )
        for chunk in ordered:
            line = cls.chunk_to_line(chunk)
            candidate = f"{accumulated}\n\n{line}" if accumulated else line
            if kept and TokenCircuitBreaker.estimate_tokens(candidate) > budget:
                break
            accumulated = candidate
            kept.append(chunk)
        return kept

    # ------------------------------------------------------------------
    # Orchestration — ASSEMBLE -> CACHE -> COMPACT
    # ------------------------------------------------------------------
    @classmethod
    def assemble(
        cls,
        context_chunks: Optional[List[Dict[str, Any]]],
        question: str,
        max_context_tokens: Optional[int] = None,
    ) -> ContextAssemblyResult:
        budget = int(max_context_tokens) if max_context_tokens is not None else cls.DEFAULT_MAX_CONTEXT_TOKENS
        kept = [c for c in (context_chunks or []) if c]
        context_text = cls.assemble_context_text(kept)
        compacted = False
        if kept and TokenCircuitBreaker.estimate_tokens(context_text) > budget:
            kept = cls._compact(kept, budget)
            context_text = cls.assemble_context_text(kept)
            compacted = True
        context_tokens = TokenCircuitBreaker.estimate_tokens(context_text)
        bundle = GroundingGuardrail.build_prefix_cached_prompt(context_chunks_text=context_text, user_question=question)
        return ContextAssemblyResult(
            context_chunks=kept,
            context_text=context_text,
            compacted=compacted,
            context_tokens=context_tokens,
            prefix_hash=bundle["prefix_hash"],
            static_prefix_tokens=bundle["static_prefix_tokens"],
            prompt=bundle["prompt"],
            citations_required=bool(kept),
        )


def assemble_context(
    context_chunks: Optional[List[Dict[str, Any]]],
    question: str,
    max_context_tokens: Optional[int] = None,
) -> ContextAssemblyResult:
    """Convenience wrapper for the Context Assembler pipeline."""
    return ContextAssembler.assemble(context_chunks, question, max_context_tokens=max_context_tokens)
