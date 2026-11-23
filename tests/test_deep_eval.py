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


def test_rag_triad_detects_hallucination_and_fails_evaluation():
    """Verify that ungrounded hallucinated claims fail with low faithfulness score."""
    question = "What is the company policy on remote work stipends?"
    context = [
        {
            "id": "2",
            "chunk_index": 0,
            "title": "Remote Work Guidelines",
            "text": "Employees may work remotely up to two days per week with manager approval.",
            "document_id": "doc_hr_2",
            "metadata": {"role": "employee"},
        }
    ]
    # Fabricated answer asserting non-existent stipend policy
    hallucinated_answer = "The company provides a $15,000 annual equipment stipend and unlimited paid travel [Doc: Remote Work Guidelines, Chunk 0]."

    score = RAGTriadEvaluator.evaluate_triad(
        question=question,
        answer=hallucinated_answer,
        context_chunks=context
    )

    assert score.faithfulness < RAGTriadEvaluator.PASS_THRESHOLD
    assert score.status in ("FAIL", "WARNING")
    assert any("ungrounded claim" in d.lower() or "hallucination" in d.lower() for d in score.diagnostics)


def test_rag_triad_graceful_unknown_admission_is_faithful():
    """Verify that honest refusal on unanswerable query yields high faithfulness."""
    question = "What is the secret deployment key for the staging cluster?"
    context = []  # No authorized context

    refusal_answer = "I do not have sufficient information in the authorized documents to answer this question."

    score = RAGTriadEvaluator.evaluate_triad(
        question=question,
        answer=refusal_answer,
        context_chunks=context
    )

    assert score.faithfulness == 1.0
    assert score.answer_relevance >= 0.80
    assert any("refusal" in d.lower() or "correctly declined" in d.lower() for d in score.diagnostics)


def test_rag_triad_context_relevance_benchmark():
    """Verify quantitative context relevance scoring against noisy vs clean chunks."""
    question = "How does pgvector HNSW halfvec compaction work?"
    
    clean_chunks = [
        {
            "chunk_index": 0,
            "title": "pgvector Optimization",
            "content": "pgvector HNSW halfvec compaction stores 16-bit float embeddings in PostgreSQL, reducing RAM footprint by 75% while maintaining cosine similarity precision.",
            "similarity": 0.95,
        }
    ]
    noisy_chunks = [
        {
            "chunk_index": 0,
            "title": "Office Cafeteria Menu",
            "content": "Today's cafeteria lunch features grilled salmon, quinoa salad, and seasonal fruit tarts.",
            "similarity": 0.15,
        }
    ]

    clean_score, _ = RAGTriadEvaluator.evaluate_context_relevance(question, clean_chunks)
    noisy_score, _ = RAGTriadEvaluator.evaluate_context_relevance(question, noisy_chunks)

    assert clean_score >= RAGTriadEvaluator.PASS_THRESHOLD
    assert noisy_score < RAGTriadEvaluator.WARNING_THRESHOLD

