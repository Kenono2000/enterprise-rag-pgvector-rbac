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
- **Pre-Commit Ruff Gate (CRITICAL)**: After modifying any `.py` file, always run `python -m ruff check --select E,W,F,I,B,S <modified_files>` (fixing any `F401` unused imports, `F841` unused variables, or other blocking findings) before completing the task so pre-commit quality gates never fail.
- **Global Rules & Skills Synced**:
  - **Website Sync**: Whenever `README.md` or its Mermaid diagrams are updated, synchronize `c:\src\abyssium-studio\src\components\MermaidBlueprints.tsx` and run `npm run lint` + `npm run build`.
  - **Minimal Markdown Whitespace**: Keep vertical whitespace to a minimum across all `.md` files (`markdown-minimal-whitespace` / `minimal-markdown`).
  - **Slack Webhook & Anonymity**: Never mention `Antigravity` in Slack payloads; use Slack IDs (`<@U0B8AF6HGAJ>`) for mentions.
  - **Trigger-to-Gate DoD & Performance**: Wire end-to-end workflow triggers (`trigger-to-gate-dod`) and back performance claims with before/after benchmarks (`prove-every-speedup`).
- Whenever planning or executing engineering tasks, check task scope against relevant skills.
- When generating or auditing code in this repository, strictly adhere to `code-reviewer` standards and verify RAG retrieval/prompts using `rag-evaluator`.
- When coordinating multi-step or multi-agent workflows, follow `fleet-planner` patterns.
- When authoring or refactoring architecture or workflow diagrams, apply `mermaid-diagram-optimizer` and adhere strictly to the MDHero (Mermaid 11.17.2) Compatibility Specification below.

## Instruction: MDHero-Compatible Mermaid Output (Mermaid 11.17.2)

> **Scope:** Every Mermaid diagram emitted must parse cleanly under Mermaid **11.17.2** (the version MDHero bundles). Treat "works in mermaid.live on a newer build" as insufficient — it must pass the 11.17.2 parser.

### 1. Always Quote Node, Edge, and Subgraph Labels
- Every `[...]`, `(...)`, `{...}`, and `>...]` label must be wrapped in double quotes: `A["Deploy (prod)"]`, `B{"Retry &lt; 3?"}`, `C("Status: OK")`.
- Quote **even when there are no special characters**, for consistency and safety.
- Subgraph titles are always quoted: `subgraph S1 ["1. Intake"]`.

### 2. Escape or Eliminate Parser-Breaking Characters
Inside quoted labels, escape XML/HTML-sensitive characters:
- `<` → `&lt;` (a bare `<` starts an HTML tag and breaks parsing)
- `>` → `&gt;`
- `&` → `&amp;` (when followed by something tag-like)
- `"` → `&quot;`
- Never put a raw `<br/>` **outside** a quoted label. Use `<br/>` only inside double quotes.
- Avoid inside labels unless double-quoted: `()` `[]` `{}` `|` `;` `:` `/` `+` `,` `?` `!` `#` `%` `@`.

### 3. Edge Labels Are Always Quoted
Write `-->|"Yes"|`, `-->|"Retry &lt; 3"|`, `-.->|"Replaced By"|`. Never `-->|Yes|` or `-->|Retry < 3|`.

### 4. Participant and Actor Aliases
In `sequenceDiagram`:
- Always quote aliases: `participant RBAC as "sanitize_roles_for_query()"`, `actor Browser as "Browser / Streamlit"`.
- Never leave a trailing `()` or a `/` in an unquoted alias.

### 5. `%%{init}%%` Directives
- Keep the directive on **one single line**.
- Use single quotes for keys/values and double-quote nothing inside: `%%{init: {'flowchart': {'nodeSpacing': 15, 'rankSpacing': 25, 'padding': 8}}}%%`.
- Do not nest multiple `init` blocks in one diagram.
- If a diagram fails to parse, **remove the `init` block first**.

### 6. Forbidden Constructs (Fail-Fast List)
- Reserved keywords as bare node IDs: `graph`, `end`, `flowchart`, `subgraph`, `class`, `style`, `click`, `linkStyle`, `direction`, `TB`, `LR`.
- `end` as a node label must be quoted: `A["end"]`.
- HTML tags other than `<br/>` inside labels.
- Emoji inside unquoted labels (quote them or drop them).
- Mixed `direction` declarations: give **each** subgraph exactly one `direction TB` (or `LR`) at the top; don't repeat it.
- Semicolons as statement terminators — omit them; one statement per line.
- Tabs — use spaces only.

### 7. Structural Rules
- Declare subgraphs **before** the cross-subgraph edges that reference them.
- Declare `style` / `classDef` lines at the **end** of the diagram.
- In `flowchart`, put subgraph-level `direction` immediately after the `subgraph` line.
- Do not use `flowchart` and `graph` interchangeably within the same project — standardize on `flowchart`.
- `sequenceDiagram`: `autonumber` goes first; `actor`/`participant` declarations next; messages after; `alt`/`else`/`end` blocks must be balanced.

### 8. Version Safety Checklist (Self-Verify Before Emitting)
1. [ ] Every label is wrapped in `"..."`.
2. [ ] No raw `<`, `>`, `&`, `"` inside quoted labels (use entities `&lt;`, `&gt;`, `&amp;`, `&quot;`).
3. [ ] Every edge label is quoted: `-->|"Label"|`.
4. [ ] `init` directive is on a single line, single-quoted, present at most once.
5. [ ] No reserved keyword used as a bare node ID.
6. [ ] Each subgraph has exactly one `direction` line at the top.
7. [ ] No tabs, no trailing semicolons.
8. [ ] `style`/`classDef` lines are at the bottom.
9. [ ] `sequenceDiagram` aliases are quoted; `alt`/`end` are balanced.
10. [ ] Target parser: Mermaid **11.17.2**.
