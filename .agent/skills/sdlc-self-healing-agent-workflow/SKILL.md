---
name: sdlc-self-healing-agent-workflow
description: Productivity skill for developing and extending the LangGraph autonomous SDLC agent, AST policy guardrails, and FastMCP tools.
---

# Autonomous SDLC Agent & LangGraph Conventions

## When to Use
- Modifying or extending the autonomous SDLC agent under `agent/`.
- Adding new agent tools, LangGraph state machine nodes, or self-healing loops (`propose -> apply -> audit -> test -> repair`).
- Developing or updating FastMCP tools under `app/mcp/`.
- Configuring AST-based policy engines and secret scanners.

## LangGraph State Machine Architecture
```text
[PROPOSE] ──► [APPLY] ──► [AUDIT (AST/Secrets)] ──► [TEST (pytest)] ──► [SUCCESS / REPAIR]
                               │                           │
                               └────── Failure ────────────┴──► [AUTO-REVERT / REPAIR]
```

## Core Agent Development Principles
1. **Deterministic Guardrails**:
   - Every agent proposed change must pass AST validation (syntax checking, no banned imports, no dangerous `eval`/`exec`).
   - Secret scanner must block commits containing unmasked API keys or service account tokens.
2. **State Immutability**:
   - In LangGraph nodes, treat the agent state dictionary as immutable or return pure delta updates.
3. **FastMCP Tool Addition**:
   - Decorate new MCP tools with `@mcp.tool()`.
   - Provide explicit docstrings and typed function arguments with Pydantic schemas.
   - Return structured error dictionaries rather than raising unhandled exceptions into the MCP transport.
