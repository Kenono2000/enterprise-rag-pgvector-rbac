---
name: tiered-subagent-routing
description: "Pairs frontier reasoning models (inherit) with Gemini Flash mechanical subagents (flash, test-triager) and Gemini Pro cross-model verifiers (pro, cross-model-judge). Use when orchestrating multi-step engineering tasks, offloading test or lint log triage, or running independent LLM-as-a-judge diff audits."
category: ai-maestro
---

# Tiered Subagent Routing (`inherit` + `flash` + `pro`)

## Overview

Complex engineering tasks combine a small number of high-reasoning architectural decisions with dozens of high-volume, mechanical lookups (searching files, grepping logs, checking lint output, or classifying test failures). Running every mechanical lookup on a frontier reasoning model inflates both tail latency and token spend, while polluting the primary conversation context window with raw stack traces.

This skill defines the **Tiered Subagent Routing Pattern** using Antigravity's `.agents/agents/*.md` customization system to pair the active frontier model (`model: inherit`) with specialized Gemini Flash (`model: flash`) and Gemini Pro (`model: pro`) subagents.

## When to use

- Running iterative test-and-repair loops (`pytest`, `npm run lint`, `npm run build`) where raw console logs would bloat the primary agent's context window.
- Classifying test or build failures by root cause (`compilation_error`, `assertion_failure`, or `timeout`) via a fast Gemini Flash subagent (`test-triager`).
- Auditing a completed workspace diff against user requirements, edge cases, and security guardrails using an independent Gemini Pro verifier (`cross-model-judge`).
- Delegating deep multi-file architectural synthesis to an isolated reasoning worker (`arch-synthesizer`, `model: inherit`).
- Designing or extending `.agents/agents/*.md` subagent definitions with explicit model tiers and minimal tool permissions.

## Core concepts

- **Three-Tier Model Allocation:**
  1. **`model: inherit` (Frontier Reasoning Tier — `arch-synthesizer`)**: Inherits the active session's frontier model for complex multi-file synthesis, PostgreSQL 16 RLS policy design, HNSW vector index tuning, and LangGraph state topology changes.
  2. **`model: flash` (High-Speed Mechanical Tier — `test-triager`)**: Offloads high-volume test execution, log grepping, and failure classification (`compilation_error`, `assertion_failure`, `timeout`) to Gemini Flash, returning only a compact structured summary.
  3. **`model: pro` (Independent Verification Tier — `cross-model-judge`)**: Runs an independent LLM-as-a-judge audit over the final workspace diff using Gemini Pro (`tools: [read]`), outputting a deterministic `PASS`/`FAIL` verdict with exact `file:L<line>` references.
- **Principle of Least Privilege (`tools` Scoping):**
  - Triage and synthesis workers receive `tools: [read, edit]`.
  - Verification judges (`cross-model-judge`) are strictly constrained to `tools: [read]` so the auditor can never mutate the diff it is judging.
- **Subagent Activation Flag (`subagent: true`):**
  Every `.agents/agents/*.md` file intended for delegation via `invoke_subagent` must include `subagent: true` in its YAML frontmatter.

## Practical workflow

1. **Ensure `.agents/agents/*.md` subagent definitions exist:**
   - **Flash Test Triager (`.agents/agents/test-triager.md`)**:
     ```markdown
     ---
     name: test-triager
     description: Runs unit tests, classifies failures, and returns a concise summary of failing assertions.
     model: flash
     subagent: true
     tools:
       - read
       - edit
     ---

     Run the requested test targets, classify any failures by root cause (compilation error, assertion failure, or timeout), and return a structured summary to the parent agent.
     ```
   - **Pro Cross-Model Judge (`.agents/agents/gemini-judge.md`)**:
     ```markdown
     ---
     name: cross-model-judge
     description: Independent LLM-as-a-judge verifier that audits diffs and edge cases using Gemini Pro.
     model: pro
     subagent: true
     tools:
       - read
     ---

     Review the current workspace diff against the user's requirements. Check for regressions, missing edge-case tests, and security issues. Output a pass/fail verdict with specific line references.
     ```

2. **Synthesize changes on the primary reasoning model (`model: inherit`):**
   Design and apply the core architectural or code changes in the primary session (or delegate isolated multi-file synthesis to `arch-synthesizer` with `Model: "inherit"`).

3. **Delegate rapid test-and-classify loops to `test-triager` (`Model: "flash"`):**
   Invoke `test-triager` with `Model: "flash"` to run unit tests or build checks and return a structured root-cause classification (`compilation_error` | `assertion_failure` | `timeout`) plus failing `file:line` targets.

4. **Repair using the concise Flash summary:**
   Feed only the compact `TriageSummary` into the reasoning model's repair step rather than dumping raw multi-thousand-line test logs.

5. **Validate the final diff with `cross-model-judge` (`Model: "pro"`):**
   Before concluding the task or opening a PR, invoke `cross-model-judge` with `Model: "pro"` to audit the workspace diff for regressions, missing edge-case tests, and AST/RBAC security violations. Proceed only when the verdict is `PASS`.

## Common pitfalls

- **Running mechanical lookups on frontier models**: Using the primary reasoning model to parse raw `pytest` or bundler logs wastes tokens and degrades reasoning focus. Always offload to `model: flash`.
- **Granting write tools to the judge subagent**: Allowing `cross-model-judge` to edit files breaks independent verification isolation. Keep the judge strictly `tools: [read]`.
- **Omitting `subagent: true` in frontmatter**: Without `subagent: true`, Antigravity will not allow the agent definition to be invoked via `invoke_subagent`.
- **Busy-waiting or polling subagents**: Never poll in a loop after calling `invoke_subagent`; end the turn and rely on Antigravity's reactive wakeup notification.
