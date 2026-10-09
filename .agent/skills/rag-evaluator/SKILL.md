---
name: rag-evaluator
description: Systematically benchmarks retrieval pipelines, context relevancy, ground-truth alignment, and hallucination rates in generative RAG systems. Use when tuning chunking, evaluating vector search, testing prompts, or running automated RAG regression suites.
category: ai-research
---

# RAG Evaluator

## Overview

Retrieval-Augmented Generation (RAG) systems fail silently. A pipeline may return fluent, grammatically flawless answers that are completely ungrounded or derived from irrelevant vector context. Traditional unit tests fail to catch semantic drift, chunk fragmentation, or subtle hallucination introduced by prompt changes or embedding model upgrades.

This skill establishes a rigorous, quantitative evaluation framework for enterprise RAG pipelines. It standardizes metric collection across the core RAG triad: **Context Relevance**, **Groundedness (Faithfulness)**, and **Answer Relevance**, providing clear diagnostic procedures to isolate whether a failure stems from ingestion chunking, vector retrieval, or LLM generation.

## When to use

- Benchmarking retrieval quality before and after changing chunk size, overlap, or embedding models.
- Evaluating vector database search (e.g., pgvector HNSW vs. IVFFlat, cosine vs. inner product).
- Auditing hallucinations or false claims in production LLM responses.
- Running automated regression tests on prompt templates and grounding instructions.
- Verifying multi-tenant isolation and RBAC filtering accuracy under test queries.

## Core concepts

- **The RAG Triad Metrics:**
  1. **Context Relevance**: Did the vector search retrieve passages that actually contain the facts needed to answer the question? (High context relevance = low noise in prompt context).
  2. **Groundedness (Faithfulness)**: Can every single factual claim made in the generated answer be directly inferred from the retrieved context excerpts? (High groundedness = zero hallucination).
  3. **Answer Relevance**: Does the final answer directly address the user's specific prompt without drifting off-topic or omitting key constraints?

- **Failure Isolation Matrix:**
  - *Good Retrieval, Bad Answer*: Prompt is too weak, model context window exceeded, or system instructions induce premature disclaimers.
  - *Bad Retrieval, Good Answer*: Model is relying on internal parametric pretraining rather than enterprise documents (high hallucination risk).
  - *Bad Retrieval, Bad Answer*: Chunking strategy severed key facts, query embedding drifted, or metadata filtering (RBAC/tenant) was overly restrictive.

- **Automated Synthetic Test Sets:**
  Benchmarking requires test triplets: `(Question, Ground-Truth Answer, Reference Context)`. Generating balanced test distributions across simple factoids, multi-hop reasoning, and out-of-domain unanswerable queries prevents false confidence.

## Practical workflow

1. **Construct or load evaluation dataset:**
   Define a representative test set of enterprise queries covering:
   - Factual single-document questions.
   - Multi-document synthesis questions.
   - Negative queries (questions whose answers do NOT exist in the corpus, expecting a graceful refusal).
   - Tenant-restricted questions (verifying RBAC isolation).

2. **Instrument trace collection:**
   Capture input query, retrieved chunk IDs, chunk text similarity scores, generation latency, and output text via OpenTelemetry spans.

3. **Compute quantitative metrics:**
   Score test cases on a 0.0 to 1.0 scale using an LLM-as-a-judge prompt or deterministic overlap scoring:
   ```markdown
   ### Evaluation Scorecard
   | Query ID | Question | Context Precision | Faithfulness | Answer Relevance | Latency (ms) | Pass/Fail |
   | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
   | Q-001 | "How is tenant isolation enforced?" | 1.00 | 1.00 | 0.95 | 420ms | PASS |
   | Q-002 | "What was Q3 revenue in 2021?" (Unanswerable) | 0.10 | 1.00 | 1.00 (Refused) | 310ms | PASS |
   | Q-003 | "Compare pgvector and pinecone pricing" | 0.45 | 0.60 | 0.70 | 850ms | FAIL (Hallucination) |
   ```

4. **Diagnose and tune pipeline:**
   - If *Context Precision* is low: Implement hybrid search (BM25 + vector embeddings) or add cross-encoder re-ranking.
   - If *Faithfulness* is low: Tighten system grounding prompts, penalize claims lacking citations, or lower LLM temperature.
   - If *Refusal rate* is excessive: Calibrate prompt instructions to permit synthesis of multiple related excerpts.

## Common pitfalls

- **Evaluating only answer fluency**: Assuming a well-written, confident response is accurate without checking the underlying source text.
- **Testing only easy single-chunk queries**: Neglecting multi-hop queries where an answer must synthesize data across three separate paragraphs.
- **Ignoring negative query testing**: Failing to test questions where the correct response is "I do not have enough information based on the provided documents."
- **Overfitting to a tiny test set**: Tuning chunk parameters for 5 test questions, destroying retrieval performance across the wider document library.
