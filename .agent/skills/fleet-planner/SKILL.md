---
name: fleet-planner
description: Coordinates multi-agent systems, subagent delegation, operational hierarchies, task routing, and shared memory structures. Use when architecting agent fleets, orchestrating parallel subtasks, or managing agent communication protocols.
category: ai-maestro
---

# Fleet Planner

## Overview

Complex software engineering, data ingestion, and multi-step research problems exceed the context window, tool limits, and reliability bounds of a single monolithic agent prompt. When an agent attempts to do everything in one turn, reasoning degrades, tool calls conflict, and error recovery fails.

The Fleet Planner skill establishes multi-agent coordination frameworks (the "AI Maestro" model). It defines how a Lead Orchestrator decomposes ambitious objectives into discrete, isolated sub-goals, delegates them to specialized worker subagents, manages asynchronous execution, and consolidates intermediate artifacts into a unified deliverable.

## When to use

- Designing multi-agent architectures (Lead Planner + Specialized Worker Agents).
- Delegating long-running, compute-heavy, or wide-breadth tasks across parallel subagents.
- Structuring inter-agent messaging protocols and shared artifact conventions.
- Preventing context pollution by offloading voluminous search and log-reading to ephemeral child agents.
- Orchestrating multi-phase workflows involving research, code generation, testing, and documentation.

## Core concepts

- **Orchestrator vs. Worker Separation:**
  - **Lead Orchestrator (Maestro)**: Owns overall project state, maintains alignment with the human operator, plans sequential milestones, dispatches tasks, and validates final results. Does NOT get bogged down reading 10,000 lines of raw logs.
  - **Worker Subagents**: Ephemeral, tightly scoped specialists (e.g., Codebase Researcher, Benchmark Runner, SQL Optimizer, A11y Auditor). They execute within an isolated context window, report findings back, and terminate.
- **Context Isolation & State Minimization:**
  Subagents protect the primary conversation history from context saturation. When a researcher explores 50 web pages or searches through 100 files, only the synthesized summary is returned to the parent agent.
- **Deterministic Handoff Contracts:**
  Every delegation must provide:
  1. *Objective & Scope*: Exactly what must be produced or verified.
  2. *Tool Constraints*: Read-only vs. write permissions vs. shell access.
  3. *Input Artifacts*: File paths, schema definitions, or test parameters.
  4. *Expected Return Format*: Structured JSON or standardized Markdown report.
- **Fail-Fast & Reactive Wakeup:**
  Orchestrators should not busy-wait or poll in loops. Systems should leverage reactive notification triggers and structured timeout limits.

## Practical workflow

1. **Deconstruct the mission:**
   Break down a complex user request into independent workstreams:
   - *Stream 1*: Fast API route audit & Swagger spec verification.
   - *Stream 2*: Database indexing benchmark on pgvector embeddings.
   - *Stream 3*: Documentation synthesis and release notes update.

2. **Define specialized subagent roles:**
   ```markdown
   - Role: Database Auditor
     Prompt: Inspect `app/db/` and verify all pgvector queries use HNSW index operators.
     Tools: File Read, Static Analysis.
   - Role: Observability Validator
     Prompt: Inspect OpenTelemetry span generation in `app/observability.py`.
     Tools: Code Search, Test Execution.
   ```

3. **Dispatch concurrent subagents:**
   Spawn subagents concurrently using the orchestrator's task delegation tool.

4. **Aggregate and synthesize findings:**
   As workers report back, verify each output against the acceptance criteria. If a worker fails, re-dispatch with corrective context rather than failing the entire workflow.

5. **Present unified deliverables to the user:**
   Assemble the collective results into an executive summary or persistent repository artifact, highlighting key decisions made across the fleet.

## Common pitfalls

- **Micro-managing subagents**: Disagreeing with intermediate scratch steps rather than evaluating the final returned deliverable.
- **Unbounded recursion**: Allowing subagents to spawn unlimited layers of nested subagents, resulting in exponential token consumption.
- **Context dumping**: Passing the entire 100,000-token parent conversation transcript to every child worker instead of passing only the relevant task prompt.
- **Silent worker failures**: Failing to check worker exit codes or error states, assuming a finished task was always successful.
