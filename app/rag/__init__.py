"""
app/rag package
Consolidates Context Engineering primitives for Zero-Trust RAG retrieval.
"""

from app.rag.context import ContextAssemblyResult, ContextAssembler, assemble_context
from app.rag.evaluator import RAGTriadScore, RAGTriadEvaluator

__all__ = [
    "ContextAssemblyResult",
    "ContextAssembler",
    "assemble_context",
    "RAGTriadScore",
    "RAGTriadEvaluator",
]
