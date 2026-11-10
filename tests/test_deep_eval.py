import pytest
from app.rag.evaluator import evaluate_rag

def test_deep_eval_faithfulness_threshold():
    # Simulate a simple RAG evaluation returning a faithfulness score
    # In real usage, evaluate_rag would run DeepEval metrics.
    result = evaluate_rag()
    # Expect a dict with 'faithfulness' key (0-1)
    faithfulness = result.get('faithfulness', 0)
    assert faithfulness >= 0.85, f"Faithfulness {faithfulness} below threshold"
