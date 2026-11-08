"""
app/rag/evaluator.py
--------------------
Quantitative RAG Triad Evaluation and Hallucination Diagnostic Engine.

Evaluates RAG pipeline executions across the core RAG Triad:
    1. Context Relevance  — signal-to-noise ratio of retrieved chunks relative to the user query.
    2. Faithfulness       — groundedness of generated claims in authorized context (zero hallucination).
    3. Answer Relevance   — alignment of final response to user query without drift or ungrounded claims.

Deterministic, high-performance, and offline-testable. Emits structured scores and actionable diagnostics
for real-time OpenTelemetry span injection and Jaeger/Azure Monitor observability.
"""

from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Literal, Optional, Set, Tuple

from pydantic import BaseModel, ConfigDict, Field

from agent.guardrails import GroundingGuardrail


# ---------------------------------------------------------------------------
# Stopwords and Tokenization Helpers (Deterministic, Zero External Dependency)
# ---------------------------------------------------------------------------

COMMON_STOPWORDS: Set[str] = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are",
    "aren't", "as", "at", "be", "because", "been", "before", "being", "below", "between", "both",
    "but", "by", "can", "can't", "cannot", "could", "couldn't", "did", "didn't", "do", "does",
    "doesn't", "doing", "don't", "down", "during", "each", "few", "for", "from", "further", "had",
    "hadn't", "has", "hasn't", "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her",
    "here", "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i", "i'd",
    "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's", "its", "itself",
    "let's", "me", "more", "most", "mustn't", "my", "myself", "no", "nor", "not", "of", "off",
    "on", "once", "only", "or", "other", "ought", "our", "ours", "ourselves", "out", "over",
    "own", "same", "shan't", "she", "she'd", "she'll", "she's", "should", "shouldn't", "so",
    "some", "such", "than", "that", "that's", "the", "their", "theirs", "them", "themselves",
    "then", "there", "there's", "these", "they", "they'd", "they'll", "they're", "they've",
    "this", "those", "through", "to", "too", "under", "until", "up", "very", "was", "wasn't",
    "we", "we'd", "we'll", "we're", "we've", "were", "weren't", "what", "what's", "when",
    "when's", "where", "where's", "which", "while", "who", "who's", "whom", "why", "why's",
    "with", "won't", "would", "wouldn't", "you", "you'd", "you'll", "you're", "you've",
    "your", "yours", "yourself", "yourselves", "tell", "please", "give", "show", "what",
}

TOKEN_PATTERN = re.compile(r"[a-zA-Z0-9_\-\.]{2,}")
SENTENCE_SPLIT_PATTERN = re.compile(r"(?<=[.!?])\s+")


def extract_keywords(text: str) -> List[str]:
    """Extract significant lowercase keyword tokens, excluding common English stopwords."""
    if not text:
        return []
    tokens = TOKEN_PATTERN.findall(text.lower())
    return [t for t in tokens if len(t) > 2 and t not in COMMON_STOPWORDS]


def extract_sentences(text: str) -> List[str]:
    """Split text into sentences for sentence-level groundedness verification."""
    if not text:
        return []
    raw = SENTENCE_SPLIT_PATTERN.split(text.strip())
    return [s.strip() for s in raw if s and len(s.strip()) > 3]


# ---------------------------------------------------------------------------
# Pydantic Schemas for RAG Triad Evaluation
# ---------------------------------------------------------------------------

class RAGTriadScore(BaseModel):
    """Structured evaluation scorecard across the core RAG Triad dimensions."""

    model_config = ConfigDict(extra="forbid")

    context_relevance: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Signal-to-noise ratio: fraction of query intent supported by retrieved chunks.",
    )
    faithfulness: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Groundedness: fraction of claims verifiable against authorized context (zero hallucination).",
    )
    answer_relevance: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Directness and specificity of the response relative to the prompt.",
    )
    composite_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Harmonic/weighted composite index across all three triad metrics.",
    )
    status: Literal["PASS", "WARNING", "FAIL"] = Field(
        ...,
        description="Categorical evaluation status based on thresholds (composite >= 0.70 & faithfulness >= 0.70 = PASS).",
    )
    diagnostics: List[str] = Field(
        default_factory=list,
        description="Diagnostic explanations, hallucination alerts, or tuning recommendations.",
    )


# ---------------------------------------------------------------------------
# Evaluator Implementation
# ---------------------------------------------------------------------------

class RAGTriadEvaluator:
    """
    Production-grade RAG Triad evaluation engine.
    Computes Context Relevance, Faithfulness (Groundedness), and Answer Relevance.
    """

    PASS_THRESHOLD: float = 0.70
    WARNING_THRESHOLD: float = 0.45

    @classmethod
    def evaluate_context_relevance(
        cls,
        question: str,
        context_chunks: Optional[List[Dict[str, Any]]],
    ) -> Tuple[float, List[str]]:
        """
        Evaluate context relevance: Did the retrieval engine fetch passages that contain
        the facts and concepts needed to answer the question?
        """
        diagnostics: List[str] = []
        if not context_chunks:
            return 0.0, ["Zero authorized context chunks retrieved (empty context)."]

        q_terms = extract_keywords(question)
        if not q_terms:
            return 1.0, []

        q_term_set = set(q_terms)
        chunk_texts = [
            f"{c.get('title', '')} {c.get('content', '') or c.get('text', '')}".lower()
            for c in context_chunks
            if c
        ]
        combined_context = " ".join(chunk_texts)
        if not combined_context.strip():
            return 0.0, ["Retrieved chunks contained empty text."]

        # Calculate coverage of query terms in retrieved chunks
        matched_terms = {t for t in q_term_set if t in combined_context}
        term_coverage = len(matched_terms) / len(q_term_set)

        # Calculate average similarity score if provided by vector search
        similarities = [
            float(c.get("similarity", 0.0))
            for c in context_chunks
            if c and c.get("similarity") is not None
        ]
        avg_sim = (sum(similarities) / len(similarities)) if similarities else 0.80

        # Context relevance is a weighted combination of term coverage (70%) and vector similarity (30%)
        raw_score = 0.70 * term_coverage + 0.30 * min(1.0, max(0.0, avg_sim))
        score = round(min(1.0, max(0.0, raw_score)), 3)

        if score < cls.WARNING_THRESHOLD:
            missing = sorted(q_term_set - matched_terms)
            diagnostics.append(
                f"Low Context Relevance ({score:.2f}): Query concepts missing from retrieved chunks: {missing[:5]}"
            )
        elif score < cls.PASS_THRESHOLD:
            diagnostics.append(f"Moderate Context Relevance ({score:.2f}): Partial query coverage.")

        return score, diagnostics

    @classmethod
    def evaluate_faithfulness(
        cls,
        answer: str,
        context_chunks: Optional[List[Dict[str, Any]]],
    ) -> Tuple[float, List[str]]:
        """
        Evaluate faithfulness (groundedness): Can every factual claim in the generated answer
        be directly inferred from the retrieved context excerpts? Detects hallucinations.
        """
        diagnostics: List[str] = []
        clean_answer = (answer or "").strip()
        if not clean_answer:
            return 0.0, ["Empty answer generated."]

        # Check for graceful refusal / unknown admission when context is absent or silent
        lower_ans = clean_answer.lower()
        is_refusal = any(phrase in lower_ans for phrase in GroundingGuardrail.UNKNOWN_ADMISSION_PHRASES)

        if not context_chunks:
            if is_refusal:
                return 1.0, ["Faithful graceful refusal: model correctly declined to answer ungrounded prompt."]
            return 0.0, ["Hallucination risk: model answered without authorized context chunks."]

        if is_refusal:
            return 1.0, ["Model recognized authorized context does not contain sufficient information."]

        # Extract context text and valid citations
        citations = GroundingGuardrail.CITATION_PATTERN.findall(clean_answer)
        valid_chunk_indices = {
            str(c.get("chunk_index", 0)) for c in context_chunks if c
        }
        chunk_texts = [
            f"{c.get('title', '')} {c.get('content', '') or c.get('text', '')}".lower()
            for c in context_chunks
            if c
        ]
        combined_context = " ".join(chunk_texts)
        context_tokens = set(extract_keywords(combined_context))

        # 1. Citation validity factor (40% weight)
        if not citations:
            citation_factor = 0.30
            diagnostics.append("Missing explicit citations in format [Doc: <Title>, Chunk <Index>].")
        else:
            cited_indices = [idx for _, idx in citations]
            valid_citations = [idx for idx in cited_indices if idx in valid_chunk_indices]
            citation_factor = (len(valid_citations) / len(citations)) if citations else 0.0
            if len(valid_citations) < len(citations):
                diagnostics.append("Hallucinated citation indices detected not present in retrieved context.")

        # 2. Sentence-level claim support factor (60% weight)
        sentences = extract_sentences(clean_answer)
        if not sentences:
            sentence_support = 1.0
        else:
            supported_sentences = 0
            for sent in sentences:
                sent_terms = extract_keywords(sent)
                if not sent_terms:
                    supported_sentences += 1
                    continue
                overlap = sum(1 for t in sent_terms if t in context_tokens)
                ratio = overlap / len(sent_terms)
                # If >= 40% of informative keywords in sentence exist in context, claim is grounded
                if ratio >= 0.40:
                    supported_sentences += 1
                else:
                    diagnostics.append(f"Potentially ungrounded claim: '{sent[:80]}...'")

            sentence_support = supported_sentences / len(sentences)

        raw_score = 0.40 * citation_factor + 0.60 * sentence_support
        score = round(min(1.0, max(0.0, raw_score)), 3)

        if score < cls.WARNING_THRESHOLD:
            diagnostics.append(f"High Hallucination Risk ({score:.2f}): Answer contains ungrounded claims.")
        elif score < cls.PASS_THRESHOLD:
            diagnostics.append(f"Moderate Faithfulness ({score:.2f}): Partial context grounding.")

        return score, diagnostics

    @classmethod
    def evaluate_answer_relevance(
        cls,
        question: str,
        answer: str,
        context_chunks: Optional[List[Dict[str, Any]]] = None,
    ) -> Tuple[float, List[str]]:
        """
        Evaluate answer relevance: Does the generated answer directly address the user's prompt
        without drifting off-topic or emitting irrelevant discourse?
        """
        diagnostics: List[str] = []
        clean_ans = (answer or "").strip()
        if not clean_ans:
            return 0.0, ["Empty answer generated."]

        lower_ans = clean_ans.lower()
        is_refusal = any(phrase in lower_ans for phrase in GroundingGuardrail.UNKNOWN_ADMISSION_PHRASES)

        # If answer correctly refused when context was missing/silent, relevance is high
        if is_refusal and (not context_chunks or len(context_chunks) == 0):
            return 1.0, []

        q_terms = extract_keywords(question)
        if not q_terms:
            return 1.0, []

        a_terms = set(extract_keywords(clean_ans))
        matched = sum(1 for t in q_terms if t in a_terms)
        term_overlap = matched / len(q_terms)

        # Length / conciseness penalty if answer is suspiciously short (< 15 chars) or repetitive
        length_penalty = 1.0
        if len(clean_ans) < 15 and not is_refusal:
            length_penalty = 0.5
            diagnostics.append("Answer is too brief to address query adequately.")

        raw_score = 0.80 * term_overlap + 0.20 * length_penalty
        score = round(min(1.0, max(0.0, raw_score)), 3)

        if score < cls.WARNING_THRESHOLD:
            diagnostics.append(f"Low Answer Relevance ({score:.2f}): Answer drifts off-topic from question.")
        elif score < cls.PASS_THRESHOLD:
            diagnostics.append(f"Moderate Answer Relevance ({score:.2f}).")

        return score, diagnostics

    @classmethod
    def evaluate_triad(
        cls,
        question: str,
        answer: str,
        context_chunks: Optional[List[Dict[str, Any]]],
    ) -> RAGTriadScore:
        """
        Execute full RAG Triad evaluation:
        Computes Context Relevance, Faithfulness, and Answer Relevance,
        and derives a composite score and PASS/WARNING/FAIL status.
        """
        cr_score, cr_diag = cls.evaluate_context_relevance(question, context_chunks)
        faith_score, faith_diag = cls.evaluate_faithfulness(answer, context_chunks)
        ar_score, ar_diag = cls.evaluate_answer_relevance(question, answer, context_chunks)

        all_diagnostics = cr_diag + faith_diag + ar_diag

        # Composite score: Faithfulness is given higher weight (1.5x) to strongly penalize hallucination
        weighted_sum = (cr_score * 1.0) + (faith_score * 1.5) + (ar_score * 1.0)
        composite = round(weighted_sum / 3.5, 3)

        if composite >= cls.PASS_THRESHOLD and faith_score >= cls.PASS_THRESHOLD:
            status = "PASS"
        elif composite >= cls.WARNING_THRESHOLD and faith_score >= cls.WARNING_THRESHOLD:
            status = "WARNING"
        else:
            status = "FAIL"

        return RAGTriadScore(
            context_relevance=cr_score,
            faithfulness=faith_score,
            answer_relevance=ar_score,
            composite_score=composite,
            status=status,
            diagnostics=all_diagnostics,
        )
