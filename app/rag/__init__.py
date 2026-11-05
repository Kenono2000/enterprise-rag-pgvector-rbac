"""
app/rag package
Consolidates Context Engineering primitives for Zero-Trust RAG retrieval.
"""

from app.rag.context import ContextAssemblyResult, ContextAssembler, assemble_context

__all__ = [
    "ContextAssemblyResult",
    "ContextAssembler",
    "assemble_context",
]
