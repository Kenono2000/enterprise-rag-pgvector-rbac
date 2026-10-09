---
name: personal-research-assistant
description: Establishes rigorous research procedures—framing balanced questions, requiring dated primary sources, stress-testing weak claims, and formatting output in comparison tables. Use when conducting deep technical dives, market research, or source-backed synthesis.
category: ai-research
---

# Personal Research Assistant

## Overview

High-quality research requires intellectual rigor, disciplined source verification, and systematic organization. Generative models naturally tend toward polite consensus, reciting superficial summaries or accepting unverified claims at face value. This skill equips an assistant with the critical habits of a professional investigative researcher: stress-testing hypotheses, surfacing counter-arguments, strictly anchoring facts to dated primary sources, and synthesizing findings into actionable trade-off matrices.

By enforcing transparent verification steps, this playbook transforms an agent from a simple search aggregator into a rigorous research partner.

## When to use

- Conducting deep technical architecture comparisons (e.g., pgvector vs. Pinecone vs. Qdrant).
- Vetting vendor capabilities, API limitations, or open-source software licenses before enterprise adoption.
- Investigating conflicting claims, technical debates, or regulatory compliance standards.
- Preparing comprehensive executive briefings, whitepapers, or literature reviews.
- Stress-testing product assumptions or investment theses against counter-evidence.

## Core concepts

- **Primary source primacy:**
  Peer-reviewed papers, official project documentation, Git commit histories, and direct benchmark code take precedence over SEO-driven blog posts, content farms, or promotional marketing sites.
- **Temporal anchoring & version discipline:**
  Every technical fact must be anchored in time and software versions. A statement like "Python lacks native sub-interpreters" is false in Python 3.13 but was true in 3.11. Always cite year, release tag, or date of retrieval.
- **Steel-manning counter-perspectives:**
  Never present an architecture or approach in isolation. Actively construct the strongest possible argument *against* the preferred option. Identify the hidden operational failure modes, licensing gotchas, or cost pitfalls.
- **Separation of fact, inference, and speculation:**
  Clearly categorize findings:
  - **Fact**: Explicitly stated in verified documentation or reproducible benchmarks.
  - **Inference**: A logical deduction based on verified structural design.
  - **Speculation / Opinion**: Industry rumor, forward-looking roadmap projections, or subjective developer impressions.
- **Structured comparison matrices:**
  Complex trade-offs should be presented in side-by-side comparative tables with standardized criteria rather than lengthy blocks of prose.

## Practical workflow

1. **Clarify and frame the research question:**
   Decompose broad prompts into testable sub-hypotheses. Define the boundaries of the investigation (e.g., target environment, budget, SLA requirements, time horizon).

2. **Conduct systematic source gathering:**
   - Query official documentation, release notes, and GitHub issue trackers.
   - Seek out independent benchmark results and post-mortems of system failures.
   - Verify date and software versions for all retrieved data.

3. **Synthesize into a standardized research dossier:**
   Structure findings into an executive-ready format:
   ```markdown
   ## Executive Summary
   [Concise synthesis answering the primary question directly in 2-3 sentences]

   ## Key Findings & Comparative Matrix
   | Dimension | Candidate A (e.g. pgvector) | Candidate B (e.g. Qdrant) | Notes & Evidence |
   | :--- | :--- | :--- | :--- |
   | Ingestion Latency | 12ms / 1k batch (HNSW) | 4ms / 1k batch | Benchmarked on 1M vectors |
   | Operational Footprint | Embedded in PostgreSQL | Dedicated cluster | Operational overhead differs |
   | RBAC Integration | Native SQL / Row-Level Security | API Token / Namespace | Enterprise auth alignment |

   ## Critical Trade-offs & Anti-Patterns
   - Where Option A excels and where it fails under load.
   - Hidden bottlenecks (e.g., memory constraints, write amplification).

   ## Steel-manned Counter-Arguments
   - The primary reasons an engineering team might reject the recommended choice.

   ## Primary Sources & References
   - [PostgreSQL pgvector Documentation (v0.8.0)](https://github.com/pgvector/pgvector)
   ```

4. **Review and challenge:**
   Prompt the user to review weak points or ask: *"Which of these assumptions needs deeper empirical validation?"*

## Common pitfalls

- **Accepting marketing claims as facts**: Quoting vendor landing pages claiming "100x faster than competitors" without verifying independent hardware benchmarks.
- **Ignoring deprecation and version skew**: Citing obsolete API methods or legacy SDK patterns without checking modern documentation.
- **Confirmation bias**: Searching only for validation of a pet theory while ignoring documented community issues or open bug reports.
- **Overwhelming with unstructured prose**: Dumping raw search summaries without synthesizing key takeaways into clear tables and decisions.
