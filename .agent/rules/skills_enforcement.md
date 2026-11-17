# Workspace Rules: Always Apply Discovered Skills

## Mandatory Skill Application Policy
- **Directive**: Always evaluate, consult, and actively apply all discovered skills (`.agent/skills/*`) across all assistant turns, plan formulations, code changes, research steps, and reviews.
- **Scope**:
  - `code-reviewer`: Must govern all diffs, code implementations, self-reviews, and PR reviews.
  - `rag-evaluator`: Must govern all vector search, chunking, prompt grounding, and RAG pipeline modifications.
  - `fleet-planner`: Must govern all subagent invocations, delegation patterns, and multi-step plans.
  - `personal-research-assistant`: Must govern all technical comparisons, benchmarks, and architectural decisions.
  - `briefing-and-inbox-triage`: Must govern all project updates, status digests, and action item triage.
  - `regex-and-cron-utility`: Must govern all scheduling, regex matching, and pipeline timers.
  - `content-brief-and-calendar-generator`: Must govern technical documentation briefs, guides, and dissemination.
  - `viral-animation-prompting`: Must govern any generative video/motion prompting requests.
  - `skill-creator`: Must govern authoring or updating any new skills.
  - `minimal-markdown`: Must govern markdown file creation and compact vertical spacing.
  - `mermaid-diagram-optimizer`: Must govern authoring, refactoring, and compact layout styling for all Mermaid diagrams.
  - `getting-started-with-muse-skills`: Must govern skill maintenance and Agent Skills formatting adherence.
  - `readme-auto-sync`: Must govern automatic documentation sync across README.md, diagrams, and website.
  - `enterprise-rag-skill`: Must govern RAG pipeline, pgvector, and RBAC security rules.
  - `fastapi-async-architecture`: Must govern FastAPI routing, asyncpg pooling, and API auth dependencies.
  - `zero-trust-rbac-coding`: Must govern in-database pgvector RBAC queries and SQL schemas.
  - `sdlc-self-healing-agent-workflow`: Must govern LangGraph SDLC orchestration, CrewAI workflows, and FastMCP tools.
  - `test-automation-and-tdd`: Must govern test suite execution, pytest fixtures, and test mocking.
  - `tiered-subagent-routing`: Must govern hierarchical subagent delegation and model tiering.
  - `hermes-issue-1-harden-oauth-pkce-state`: Must govern OAuth 2.0 PKCE state verification and HMAC cookies.
