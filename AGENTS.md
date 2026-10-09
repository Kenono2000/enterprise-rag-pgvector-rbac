# Project Agent Directives & Operational Rules

## Mandatory Skill Execution Policy

**CRITICAL DIRECTIVE**: Always evaluate, consult, and actively apply all discovered skills across the workspace and local environment during any interaction, plan, code modification, or review.

### Discovered Skills Inventory (`.agent/skills/`)
1. **`getting-started-with-muse-skills`**: Baseline onboarding and formatting compliance for Agent Skills conventions.
2. **`code-reviewer`**: Enforce structured, layered review discipline (`correctness` -> `design` -> `readability` -> `security` -> `performance`) with standardized comment taxonomy (`blocking:`, `suggestion:`, `question:`, `nit:`).
3. **`skill-creator`**: Trigger-first design, strict validation, and five-section structure for new capabilities.
4. **`viral-animation-prompting`**: 5-layer video and motion directive generation for generative media.
5. **`personal-research-assistant`**: Rigorous investigative procedures: primary source primacy, temporal anchoring, steel-manning counter-arguments, and comparison matrices.
6. **`briefing-and-inbox-triage`**: 4-bucket triage model (Act Today / Delegate / Defer / Archive), action item extraction, and structured briefings.
7. **`rag-evaluator`**: Benchmark retrieval pipelines, verify the RAG Triad (Context Relevance, Faithfulness, Answer Relevance), and diagnose hallucinations.
8. **`fleet-planner`**: Multi-agent coordination, Lead Orchestrator vs. Worker subagent roles, context isolation, and deterministic contracts.
9. **`content-brief-and-calendar-generator`**: Search intent analysis, developer persona profiling, and multi-week editorial scheduling.
10. **`regex-and-cron-utility`**: Dialect validation, ReDoS prevention, regex test matrices, and 5/6-field cron schedule breakdowns.

### Behavioral Enforcement
- Whenever planning or executing engineering tasks, check task scope against relevant skills.
- When generating or auditing code in this repository, strictly adhere to `code-reviewer` standards and verify RAG retrieval/prompts using `rag-evaluator`.
- When coordinating multi-step or multi-agent workflows, follow `fleet-planner` patterns.
