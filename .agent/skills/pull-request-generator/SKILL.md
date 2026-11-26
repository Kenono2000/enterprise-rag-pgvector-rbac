---
name: pull-request-generator
description: Generates standardized, audit-ready Pull Request titles and descriptions in GitHub Flavored Markdown (GFM) format. Use whenever the user asks to generate, draft, prepare, or format pull request details, PR descriptions, or merge summaries.
category: workflow-automation
---
# Pull Request Generator Skill
## Overview
This skill provides a deterministic framework for generating comprehensive, audit-ready, copy-pasteable Pull Request titles and descriptions formatted in GitHub Flavored Markdown (GFM). It guarantees transparent disclosure of changed behavior, screen-to-contract mappings, schema migrations, automated test evidence, and remaining release gates without missing details or bloated formatting.
## When to use
- User asks to "generate pull request detail", "write a PR description", "draft PR", or "prepare pull request".
- Completing a feature branch, bug fix, or infra cutover ticket ready for PR review and merge.
- Summarizing complex multi-file diffs across backend, frontend, schema, contracts, and test suites into a structured review artifact.
## Core concepts & Format Standards
1. **Conventional Commits PR Title**:
   Always provide a standardized title: `<type>(<scope>): <concise summary> (#<issue>)`
   Examples: `feat(admin): deliver live fleet safety, dock, alert noise, and freshness (#482)`, `fix(backend): restore deviceRegistry index and align claim codes (#481)`.
2. **Copy-Paste Ready GFM Block**:
   Always present the complete PR description inside a top-level fenced code block (` ```markdown ... ``` `) so the developer can copy and paste directly into the GitHub PR editor without manual reformatting.
3. **Canonical PR Structure**:
   - `## Summary`: High-level problem statement, target issue link (`Resolves #XYZ`), and delivery scope.
   - `## Endpoints / Changes Delivered`: Structured table mapping Screen/Route, Ticket Journey, Client Contract, Backend Endpoint, and Scope / Access Boundary.
   - `## Schema & Data Model Alignments`: Explicit list of new tables, restored/added indexes, legacy schema widenings, or validator modifications.
   - `## Verification & QA Scenarios`:
     - Exact test commands executed across packages.
     - Quantified test outcomes (passed / total).
     - BDD scenario IDs or behavioral assertions verified.
   - `## Documentation & Artifacts`: Links to proposal documents (`.lev/pm/proposals/`), architecture designs, or API parity suites.
   - `## Remaining Gates & Rollout Posture`: Target integration branch, deployment order, or runtime checks.
4. **Minimal Whitespace**:
   Adhere to the `markdown-minimal-whitespace` standard: 0 blank lines after headings, compact GFM tables, tight lists, and zero decorative horizontal rules (`---`).
## Practical workflow
1. **Analyze Branch Diff & History**:
   - Run `git log origin/main..HEAD --oneline` (or integration branch) to inspect all committed work.
   - Run `git status` and `git diff` to identify all changed files, schema alterations, and test suites.
2. **Extract Metrics & Evidence**:
   - Collect exact test commands, passing counts, and coverage across backend and frontend packages.
   - Identify touched tables, indexes, and API contracts.
3. **Synthesize Screen-to-Contract Table**:
   - Group delivered capabilities by screen, route, contract, and security scope.
4. **Generate Output**:
   - Present the PR Title in a code block.
   - Present the full GFM PR body in a ` ```markdown ` fenced block.
## Output Template
```markdown
## Summary
Resolves #<ISSUE_ID>. <High-level summary of problem, architectural changes, and delivered functionality>.

## Endpoints / Changes Delivered
| Screen & Route | Journey / Purpose | Client Contract | Backend Endpoint | Scope / Access Boundary |
|---|---|---|---|---|
| `<ROUTE>` | <PURPOSE> | `<CLIENT_CONTRACT>` | `<ENDPOINT>` | <PERMISSIONS_AND_AUDIT> |

## Schema & Data Model Alignments
- **<CATEGORY>**: <Specific schema changes, indexes added, or validator updates>.

## Verification & QA Scenarios
- **<SUITE_NAME>**: `<COMMAND>` -> **<PASSED>/<TOTAL> passed**.
- **Verified Scenarios**:
  - `<SCENARIO_ID>`: <Key behaviors tested>.

## Non-Binding Proposal & Documentation
- Documented in `<PROPOSAL_PATH>`.
```
## Common pitfalls
- **Uncopyable Snippets**: Scattering PR text across conversation prose instead of providing a single copy-pasteable Markdown block.
- **Omitted Test Evidence**: Saying "tests pass" without specifying exact commands and passed/total counts.
- **Silent Schema Migrations**: Failing to highlight new indexes, table spreads, or dropped fields that affect production runtime.
