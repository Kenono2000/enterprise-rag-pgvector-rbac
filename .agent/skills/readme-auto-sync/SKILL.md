---
name: readme-auto-sync
description: Mandatory skill to always review and update README.md after making any code modifications, new feature additions, API updates, schema migrations, or test changes, AND always synchronize the abyssium-studio website (including all Mermaid diagrams in MermaidBlueprints.tsx) whenever README.md is updated.
---

# README.md, Mermaid Architecture & Website Auto-Synchronization Skill

## When to Use
- **Mandatory Trigger 1 (Code -> README.md)**: Run this workflow after **any** code change, refactoring, bug fix, schema modification, or feature implementation in the repository.
- **Mandatory Trigger 2 (README.md -> Website)**: Whenever `README.md` (in `c:\src\abyssium-studio\README.md` or `c:\src\enterprise-rag-pgvector-rbac\README.md`) is updated—especially when Mermaid diagrams, architecture specs, metrics, or sections change—you **MUST** immediately update the React website in `c:\src\abyssium-studio` (including `src/components/MermaidBlueprints.tsx` and relevant components) and verify with `npm run build`.
- When adding, updating, or deleting endpoints, CLI scripts, database tables, or environment variables.
- When components, data flows, agent states, or integrations are modified.
- When test suites or test counts change.

## When NOT to Use
- Pure read-only queries where no codebase or documentation files were modified.

## Auto-Update Checklist

Whenever you modify code or `README.md`, perform this synchronization before concluding the task:

### 1. Identify the Scope of the Change
- Were new FastAPI endpoints, route parameters, or auth dependencies introduced?
- Were database schemas, pgvector settings, or indexes changed in `schema.sql` or `app/db/`?
- Were agent nodes, state transitions, or guardrails in `agent/` modified?
- Were FastMCP tools in `app/mcp/` added or updated?
- Were tests added, renamed, or modified affecting the test count?
- Were any sections, metrics, or ` ```mermaid ` diagrams added or modified in `README.md`?

### 2. Synchronize Mermaid Architecture & Flow Diagrams in `README.md` (CRITICAL)
- **Locate Diagrams**: Inspect all ` ```mermaid ` blocks in [enterprise-rag-pgvector-rbac/README.md](file:///C:/src/enterprise-rag-pgvector-rbac/README.md) and [abyssium-studio/README.md](file:///C:/src/abyssium-studio/README.md).
- **Update Components & Subgraphs**:
  - Add newly created microservices, API routes, or databases to the appropriate subgraph.
  - Update node labels and descriptions (e.g., ports, endpoints, model names, table names).
- **Update Data Flow Arrows & Sequence Steps**:
  - Keep numbered communication steps sequentially accurate.
  - Add or adjust links reflecting new dependencies or calls.
- **Validate Mermaid Syntax**:
  - Ensure labels with special characters like parentheses, brackets, or colons are properly double-quoted (e.g., `api["API Gateway (POST /api/v1/query)"]`).
  - Avoid raw HTML tags in labels; use `<br/>` for line breaks.

### 3. Synchronize `README.md` Sections
- **Codebase Organization**: Update file trees if files/folders were created or removed.
- **Architectural Deep Dive (8 Engineering Layers)**: Update the relevant layer section to reflect actual implementation details.
- **Testing & Verification Guide**: Keep test counts and command examples synchronized.
- **Quickstart & Setup**: Add any new environment variables or startup flags.

### 4. Synchronize Website (`c:\src\abyssium-studio`) & Live Mermaid Diagrams (MANDATORY)
Whenever `README.md` or any of its Mermaid diagrams are updated:
1. **Update [`src/components/MermaidBlueprints.tsx`](file:///c:/src/abyssium-studio/src/components/MermaidBlueprints.tsx)**:
   - Synchronize `README_MERMAID_DIAGRAMS` so every added, modified, or removed ` ```mermaid ` diagram in `README.md` is accurately reflected in the live website's interactive Mermaid blueprint gallery (preserving dark-mode obsidian styling `#0f1623`, `#080c14`, `#06b6d4`, `#10b981`).
2. **Update Corresponding Website Sections**:
   - If architectural metrics, stack tags, endpoints, or system specs changed in `README.md`, synchronize [`Hero.tsx`](file:///c:/src/abyssium-studio/src/components/Hero.tsx), [`ProjectCard.tsx`](file:///c:/src/abyssium-studio/src/components/ProjectCard.tsx), [`ArchitectureDiagram.tsx`](file:///c:/src/abyssium-studio/src/components/ArchitectureDiagram.tsx), [`ExperienceTimeline.tsx`](file:///c:/src/abyssium-studio/src/components/ExperienceTimeline.tsx), or [`ContactFooter.tsx`](file:///c:/src/abyssium-studio/src/components/ContactFooter.tsx).
3. **Verify Production Build**:
   - Run `npm run lint` and `npm run build` in `c:\src\abyssium-studio` to guarantee zero build or rendering errors.

### 5. Quality & Formatting Rules
- Preserve existing markdown formatting, badge styles, and visual theme.
- Keep the tone professional, structured, and consistent with the rest of the documentation.
- Verify that all relative markdown links and anchors remain valid.
