## Goal
Fix dependency conflicts in `requirements.txt` so that `pip install -r requirements.txt` completes successfully, enabling the project's CI/CD and development environments to install without errors.

## Decisions Made

### 1. CrewAI Version Pinning
- **Change**: `crewai>=1.15.18`, `crewai-core>=1.15.18`, `crewai-tools>=1.15.18` → `crewai==1.15.43`, `crewai-core==1.15.43`, `crewai-tools==1.15.43`
- **Rationale**: The `>=` specifiers conflicted with `crewai-tools 1.15.43`'s pinned dependency on `crewai==1.15.43`. Pinned versions resolve the conflict deterministically.
- **Source**: pip error `ResolutionImpossible` from conflicting `crewai` version ranges.

### 2. httpx Version Relaxation
- **Change**: `httpx==0.28.1` → `httpx>=0.27.1,<1.0.0`
- **Rationale**: The strict `==0.28.1` conflicted with `firebase_admin 7.7.0`'s dependency on `httpx==0.28.1` and `crewai 1.15.43`'s transitive dependency on `httpx~=0.28.1`. Relaxing to `<1.0.0` allows pip's resolver to find a compatible patch version.
- **Source**: pip error citing `firebase-admin 7.7.0 depends on httpx==0.28.1` and `crewai 1.15.43 depends on httpx~=0.28.1`.

### 3. New Feature Integration (Completed)
- **incident_agent/tools.py**: Added `tool_security_exposure_score(service)` — calculates a 0.0–1.0 risk score based on recent changes, error logs, and open incidents. Registered in `TOOL_SPECS`.
- **agent/workflow.py**: Updated `AutonomyMaturityEvaluator` to evaluate a `low_security_exposure` signal. If the exposure score < 0.5, adds 6 points to the Security & Governance pillar (Pillar 8), incentivizing stable service health as part of SDLC autonomy progression.

## Verified Facts
| Fact | Source |
|------|--------|
| `pip install -r requirements.txt` fails with `ResolutionImpossible` when `crewai>=1.15.18` conflicts with `crewai-tools 1.15.43` | pip stderr output in session |
| `httpx==0.28.1` conflicts with `firebase_admin 7.7.0` and `crewai 1.15.43` | pip stderr output in session |
| `AutonomyMaturityEvaluator` now checks `signals["low_security_exposure"]` and awards +6 points if `True` | `agent/workflow.py` edit (line ~246) |
| `tool_security_exposure_score` implemented in `incident_agent/tools.py` and dispatched via `TOOL_SPECS` | `incident_agent/tools.py` edit |

## Unresolved Questions
- The `pip install` process appears to be hanging on `fastmcp-slim` version backtracking. The current `requirements.txt` has `fastmcp>=4.0.10,<5.0.0`, which is pulling in many intermediate `fastmcp-slim` candidates. A pinned version (e.g., `fastmcp==4.2.1`) may be required to force a clean resolve, or the `--cached` flag should be used aggressively.

## Next Actions
1. **Retry pip install** with aggressive caching (`--cache-dir`) and/or pin `fastmcp` to the already-installed version `4.2.1` to break the backtracking loop.
2. **Verify the installed tools** by running `python -c "from incident_agent.tools import tool_security_exposure_score; print(tool_security_exposure_score('main-app'))"` to confirm the new security exposure tool works.
3. **Run the maturity evaluator** via `python -c "from agent.workflow import AutonomyMaturityEvaluator; r = AutonomyMaturityEvaluator.evaluate_repository('C:\\src\\enterprise-rag-pgvector-rbac'); print(r.maturity_level, r.total_score)"` to confirm the new security pillar metric is active.