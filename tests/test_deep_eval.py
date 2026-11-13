import pytest
from app.rag.evaluator import RAGTriadEvaluator

def test_rag_triad_faithfulness_and_relevance():
    """Verify that RAG Triad evaluation enforces >= 0.85 faithfulness and quality thresholds with grounded citations."""
    question = "What are the RBAC requirements for database access?"
    context = [
        {
            "id": "1",
            "chunk_index": 0,
            "title": "Security Architecture",
            "text": "All database access requires zero-trust RBAC role evaluation and JWT validation.",
            "document_id": "doc_sec_1",
            "metadata": {"role": "admin"},
        }
    ]
    # Grounded answer with explicit citation [Doc: Security Architecture, Chunk 0]
    answer = "All database access requires zero-trust RBAC role evaluation and JWT validation [Doc: Security Architecture, Chunk 0]."
    
    score = RAGTriadEvaluator.evaluate_triad(
        question=question,
        answer=answer,
        context_chunks=context
    )
    
    assert score.faithfulness >= 0.85, f"Faithfulness {score.faithfulness} below 0.85"
    assert score.answer_relevance >= 0.80, f"Answer relevance {score.answer_relevance} below 0.80"
    assert score.status == "PASS", f"Evaluation status was {score.status}"
