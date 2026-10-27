---
name: sdlc-self-healing-agent-workflow
description: Productivity skill for developing and extending the LangGraph autonomous SDLC agent, CrewAI role-based crew orchestration, Hermes Agent SKILL.md synthesis, AST policy guardrails, and FastMCP tools.
---
# Autonomous SDLC Agent: LangGraph + CrewAI + Hermes Agent Conventions
## When to Use
- Modifying or extending the autonomous SDLC agent under `agent/`.
- Adding new agent tools, LangGraph state machine nodes, CrewAI role specs (`SDLCCrewOrchestrator`), or Hermes Agent skill distillation (`HermesSkillSynthesizer`).
- Developing or updating FastMCP tools under `app/mcp/`.
- Configuring AST-based policy engines and secret scanners.
## Tri-Paradigm SDLC State Machine Architecture
```text
[INITIALIZE (Hermes Skill Recall)] ──► [PROPOSE (CrewAI Architect)] ──► [APPLY (Snapshot)] ──► [AUDIT (Deep AST + Pro Judge)] ──► [TEST (Flash Triager, 30s Timeout)] ──► [HERMES SKILL.md + RL] ──► [FINALIZE (HITL Gate / PR)]
                                                                               ▲                           │                                        │
                                                                               ├─── [REPAIR (<=3x)] ◄──────┴─────── Recoverable Failure ────────────┤
                                                                               └─── [ATOMIC ROLLBACK] ◄──────────── Secret / Max Attempts ──────────┘
```
## Core Agent Development Principles
1. **LangChain / LangGraph State Machine (`LangGraphSDLCWorkflow`)**:
   - Maintain deterministic cyclic state transitions with `MemorySaver` checkpointing, per-node OpenTelemetry spans (`tracer.trace_span("sdlc.<node>")`), and atomic file rollback (`rollback_patches`) on failure.
2. **CrewAI Role-Playing Crew (`SDLCCrewOrchestrator`)**:
   - Bind every subagent to an explicit `CrewAgentSpec` (`role`, `goal`, `backstory`, `model_tier` across `inherit`/`pro`/`flash`) and append structured `CrewTaskOutput` records to `crew_trace`.
3. **Hermes Agent Self-Improving Runtime (`HermesSkillSynthesizer`)**:
   - Recall matching `.agent/skills/hermes-*/SKILL.md` playbooks during `initialize` (`recall_relevant_skills`), distill verified resolutions into portable `SKILL.md` files (`HermesSkillArtifact`), and export ShareGPT trajectories (`HermesTrajectoryRecord`).
4. **Deterministic Guardrails, Autonomy Ladder & FastMCP Tools**:
   - Enforce deep AST checks (`eval`, `exec`, `os.system`, `subprocess(shell=True)`, `pickle.loads`), protected-path blocks (`.env`, `agent/guardrails.py`), `TokenCircuitBreaker` per issue, 30s subprocess timeouts, and `ApprovalCard` HITL risk gating (`low_risk` vs `high_risk`).
