---
name: code-reviewer
description: Structured code review discipline: correctness, design, readability, and security checks with actionable feedback. Use when reviewing diffs, PRs, or code snippets before merge or after writing.
category: development
---

# Code Reviewer

## Overview

A code review is not a spell-check. It is the last structured chance to catch bugs, design drift, and security vulnerabilities before they ship — and the premier mentoring surface for engineering teams. This skill turns review into a repeatable discipline: a layered checklist (correctness → design → readability → security → performance), standardized comment conventions that keep feedback actionable and constructive, and clear decision rules for approval stances.

Good reviewers optimize for **throughput with safety**: catch what matters, avoid relitigating settled styling or linting issues, and leave the codebase — and the author — better than they found them.

## When to use

- Reviewing a pull request or merge request before merging to the trunk branch.
- Performing a disciplined self-review on your own diff before tagging team members.
- Auditing AI-generated code snippets or refactors before accepting changes.
- Onboarding new engineering contributors to establish shared engineering standards.
- Conducting high-stakes audits on emergency hotfixes or production patches under time constraints.

## Core concepts

- **Layered review hierarchy:**
  Execute reviews in descending priority. Do not get bogged down in variable names if the core algorithm has an unhandled null pointer or SQL injection:
  1. **Correctness**: Does the code execute what it claims? Check boundary cases, null values, off-by-one loops, async event loop handling, and error/exception paths.
  2. **Design & Architecture**: Does it adhere to project boundaries? Check interface contracts, separation of concerns, single-responsibility, and coupling.
  3. **Readability & Maintainability**: Can another engineer understand this code in one pass? Are complex regexes, concurrency primitives, or bitwise operations properly commented?
  4. **Security**: Validate against the OWASP Top 10 (SQL injection, SSRF, authorization bypass, unsafe deserialization, hardcoded secrets, timing attacks).
  5. **Performance**: Inspect known latency and memory bottlenecks (N+1 database queries, unindexed lookups, unbounded in-memory aggregations, leakages of open sockets or db connections).

- **Standardized comment taxonomy:**
  Use clear prefixes so the author immediately knows the expected action:
  - `blocking:` Must be resolved before merging (functional defect, security issue, broken contract, lack of essential tests).
  - `suggestion:` A concrete improvement or alternative implementation (provide code snippets whenever possible). Author may adopt or decline with rationale.
  - `question:` A request for clarification or context, not passive-aggressive criticism.
  - `nit:` Minor style preference or cosmetic detail. Non-blocking; author can merge without addressing.

- **Explicit approval stances:**
  - **Approve**: Code is safe, functional, and ready to ship.
  - **Approve with comments**: Only non-blocking nits or minor optional suggestions remain. Author may merge directly after addressing.
  - **Request changes**: Blocking defects, security flaws, or missing tests require author remediation and a subsequent re-review.
  - **Hold**: Fundamental architectural or scope mismatch requiring a sync before further code edits.

## Practical workflow

1. **Understand context and intent:**
   Read the PR description, linked issue tickets, and design requirements before examining the diff. Understand the problem before criticizing the solution.

2. **Self-review verification:**
   Verify that the author has run unit and integration test suites, updated documentation, and that CI checks (linters, static analyzers) have passed cleanly.

3. **Line-by-line inspection:**
   Walk through changed files systematically. Check imports, modified function signatures, database schema migrations, and concurrency locks.

4. **Formulate structured feedback:**
   Group feedback logically. Start with an executive summary highlighting what was done well, followed by grouped issues sorted by severity (`blocking:`, `suggestion:`, `nit:`).
   ```markdown
   ### Review Summary
   Great work on adding tracing to the MCP gateway. The span propagation works smoothly.
   
   #### Blocking Issues
   - `blocking:` In `app/db/llm.py:42`, the async client is instantiated outside the running event loop, which causes `RuntimeError: Event loop is closed` on concurrent requests. Please wrap it in a thread-safe getter or lifecycle hook.
   
   #### Suggestions
   - `suggestion:` Consider adding an integration test in `tests/test_gateway.py` asserting that span tags match OpenTelemetry semantic conventions.
   ```

5. **Re-reviewing updates:**
   When reviewing revisions, inspect only the new incremental commit diffs rather than re-reading the entire branch, resolving discussion threads as items are verified.

## Common pitfalls

- **Reviewing style instead of logic**: Bickering over formatting or imports instead of letting automated formatters (Ruff, Black, ESLint) do the work.
- **Ghosting reviews**: Leaving PRs unreviewed for multiple days, causing merge conflicts and developer friction. Timebox initial reviews to within 24 hours.
- **Vague critiques**: Commenting "this looks messy" or "re-architect this" without offering concrete architectural alternatives or code snippets.
- **Rubber-stamping**: Clicking "Approve" on a 1,000-line diff in two minutes without reading the business logic or checking edge cases.
