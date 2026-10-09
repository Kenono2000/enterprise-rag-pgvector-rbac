---
name: readme-auto-sync
description: Mandatory skill to always review and update README.md after making any code modifications, new feature additions, API updates, schema migrations, or test changes, including synchronizing all Mermaid architecture diagrams.
---

# README.md & Mermaid Architecture Auto-Synchronization Skill

## When to Use
- **Mandatory Trigger**: Run this workflow after **any** code change, refactoring, bug fix, schema modification, or feature implementation in the repository.
- When adding, updating, or deleting endpoints, CLI scripts, database tables, or environment variables.
- When components, data flows, agent states, or integrations are modified.
- When test suites or test counts change.

## When NOT to Use
- Pure read-only queries or documentation-only queries where no codebase files were modified.

## Auto-Update Checklist

Whenever you modify code in this repository, perform this post-change synchronization before concluding the task:

### 1. Identify the Scope of the Change
- Were new FastAPI endpoints, route parameters, or auth dependencies introduced?
- Were database schemas, pgvector settings, or indexes changed in `schema.sql` or `app/db/`?
- Were agent nodes, state transitions, or guardrails in `agent/` modified?
- Were FastMCP tools in `app/mcp/` added or updated?
- Were tests added, renamed, or modified affecting the test count?

### 2. Synchronize Mermaid Architecture & Flow Diagrams (CRITICAL)
- **Locate Diagrams**: Inspect all ` ```mermaid ` blocks in [README.md](file:///C:/src/enterprise-rag-pgvector-rbac/README.md) (e.g., `## 🏛️ System Architecture` flowchart, SDLC agent state diagrams).
- **Update Components & Subgraphs**:
  - Add newly created microservices, API routes, or databases to the appropriate subgraph.
  - Update node labels and descriptions (e.g., ports, endpoints, model names, table names).
- **Update Data Flow Arrows & Sequence Steps**:
  - Keep numbered communication steps (e.g., `1. PKCE Auth Code`, `8. GIN Filter + Cosine Distance`) sequentially accurate.
  - Add or adjust links reflecting new dependencies or calls (e.g., `mcp_client`, `Agent`, `embed`, `pool`, `db`).
- **Validate Mermaid Syntax**:
  - Ensure labels with special characters like parentheses, brackets, or colons are properly double-quoted (e.g., `api["API Gateway (POST /api/v1/query)"]`).
  - Avoid raw HTML tags in labels; use `<br/>` for line breaks.

### 3. Synchronize README Sections
- **Codebase Organization**: Update file trees if files/folders were created or removed.
- **Architectural Deep Dive (8 Engineering Layers)**: Update the relevant layer section to reflect actual implementation details.
- **Testing & Verification Guide**: Keep test counts and command examples synchronized.
- **Quickstart & Setup**: Add any new environment variables or startup flags.

### 4. Quality & Formatting Rules
- Preserve existing markdown formatting, badge styles, and visual theme.
- Keep the tone professional, structured, and consistent with the rest of the documentation.
- Verify that all relative markdown links and anchors remain valid.
