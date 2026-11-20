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
11. **`mermaid-diagram-optimizer`**: Compact multi-stage flowchart restructuring, 16:9/4:3 aspect ratio targeting, line wrapping (`<br/>` <= 22 chars), universal quoted syntax, and Dagre rank splay prevention.
12. **`tiered-subagent-routing`**: Pairs frontier reasoning models (`model: inherit`) with Gemini Flash mechanical log-triage subagents (`model: flash`, `test-triager`) and Gemini Pro independent LLM-as-a-judge diff verifiers (`model: pro`, `cross-model-judge`).
13. **`minimal-markdown`**: Enforces ultra-compact vertical whitespace, single blank lines, zero trailing spaces, and stripped interior lines in diagrams/code blocks across all Markdown files.
14. **`readme-auto-sync`**: Mandatory automatic synchronization of README.md, architecture layers, Mermaid diagrams, and test suite counts after code changes.
15. **`enterprise-rag-skill`**: Project-specific domain skill for enterprise RAG pipelines, pgvector indexing, and RBAC security rules.
16. **`fastapi-async-architecture`**: High-throughput FastAPI route engineering, asyncpg pooling, Pydantic schemas, and JWT dependencies.
17. **`zero-trust-rbac-coding`**: Shift-left in-database zero-trust pgvector RBAC queries, GIN pre-filtering, and schema changes.
18. **`sdlc-self-healing-agent-workflow`**: Autonomous SDLC agent development, LangGraph state persistence, CrewAI crew roles, and FastMCP tools.
19. **`test-automation-and-tdd`**: Test authoring, pytest suites, asyncio isolation, and database/LLM mock setups.
20. **`hermes-issue-1-harden-oauth-pkce-state`**: Hardened OAuth 2.0 PKCE state verification, timing-safe validation, and HMAC cookies.
21. **`default-skill`**: Standard baseline template for scaffolding Agent Skills.

### Behavioral Enforcement
- **Single-File Documentation Policy (CRITICAL)**: All project, architectural, runbook, and migration markdown documentation MUST reside exclusively in [`README.md`](file:///D:/src/enterprise-rag-pgvector-rbac/README.md). Never create separate documentation `.md` files in `docs/` or root directories—always consolidate and maintain all documentation directly inside `README.md`.
- Whenever planning or executing engineering tasks, check task scope against relevant skills.
- When generating or auditing code in this repository, strictly adhere to `code-reviewer` standards and verify RAG retrieval/prompts using `rag-evaluator`.
- When coordinating multi-step or multi-agent workflows, follow `fleet-planner` patterns.
- When authoring or refactoring architecture or workflow diagrams, apply `mermaid-diagram-optimizer`.
