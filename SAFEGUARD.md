# Technical Note: Production-Grade AI Code Agent Quality Control & Guardrails
**Quick Nav:** [1. Summary](#1-executive-summary) · [2. Standards](#2-industry-standards--frameworks) · [3. 5-Layer Architecture](#3-the-5-layer-architecture) · [4. Blocking](#4-how-layers-block-failed-code) · [5. SDLC](#5-sdlc-positioning) · [6. Commit Proving](#6-manual-commit-quality-proving) · [7. Scaling](#7-scaling-across-enterprise-dev-teams) · [8. Q&A](#8-interview-qa-cheat-sheet) · [9. DoD Rule](#9-implementation-rule-trigger-to-gate-definition-of-done) · [10. Evidence](#10-verification-evidence) · [11. Lessons](#11-lessons-learned)
## 1. Executive Summary
Production AI code agent safety cannot be achieved through prompt engineering alone. LLMs are probabilistic; therefore quality control must be **deterministic defense-in-depth**. The architecture wraps the agent in least-privilege boundaries, intercepts proposed writes in memory with AST and secret policies before they hit disk, enforces open-source lint/format standards (Ruff), and requires verifiable quality proofs at commit/CI time.
**Framing:** "You cannot prompt-engineer your way to production safety. We pair probabilistic LLM reasoning with deterministic enforcement."
## 2. Industry Standards & Frameworks
### 2.1 OWASP Top 10 for Agentic Applications (ASI Top 10)
| Risk | Description | Coding Agent Impact |
|------|-------------|---------------------|
| ASI01 Goal Hijack | Indirect prompt injection via issues, PRs, READMEs | Override phrases hijack agent goals |
| ASI02 Tool Misuse | Over-permissioned shell/file tools | Destructive commands |
| ASI03 Privilege Abuse | Broad service tokens | Credential exfiltration |
| ASI04 Agentic Supply Chain | Hallucinated/malicious packages, compromised MCP servers | Slopsquatting |
| ASI05 Unexpected Code Execution | Unvalidated dynamic code/infra scripts | RCE |
| ASI06 Memory/Context Poisoning | Poisoned rule files (.cursorrules, CLAUDE.md) | Persistent instruction injection |
### 2.2 OWASP AISVS (Appendix C – AI-Assisted Secure Coding)
Defines verification checklists (L1–L3) for tool qualification, input restrictions, threat modeling for automated PRs, and mandatory human-in-the-loop (HITL) gates.
### 2.3 OWASP Agent Control Standard (ACS)
Open framework for runtime enforcement—portable middleware hooks to block high-risk commands or unauthorized file access.
## 3. The 5-Layer Architecture
```mermaid
%%{init: {'flowchart': {'nodeSpacing': 15, 'rankSpacing': 25, 'padding': 8}}}%%
flowchart LR
  subgraph L1 ["1. Input Hygiene"]
    direction TB
    A1["Untrusted Text<br/>(Issues, PRs, Docs)"] --> A2["PromptInjectionSanitizer<br/>Fence &amp; Detect"]
  end
  subgraph L2 ["2. Scope Control"]
    direction TB
    B1["Target Path"] --> B2["ScopeGuard<br/>SCP001-SCP004"]
  end
  subgraph L3 ["3. Pre-Write Gate"]
    direction TB
    C1["In-Memory Code"] --> C2["ASTPolicyGate<br/>AST001-AST007"] --> C3["SecretScanner<br/>SEC001-SEC005"]
  end
  subgraph L4 ["4. Standards Gate"]
    direction TB
    D1["Staged Files"] --> D2["RuffStandardsGate<br/>E,W,F,I,B,S + Format"]
  end
  subgraph L5 ["5. Commit Proving"]
    direction TB
    E1["QualityControlPipeline"] --> E2["QualityProofAttestation<br/>SHA-256 + Audit ID"]
  end
  L1 -->|"Fenced Data"| L2
  L2 -->|"Allowed Path"| L3
  L3 -->|"Clean AST &amp; No Secrets"| L4
  L4 -->|"Ruff Passed"| L5
  C2 -->|"Blocking Finding"| F1["Self-Healing Feedback<br/>to_agent_feedback()"]
  F1 -.->|"Retry"| C1
```
| Layer | Mechanism | What It Prevents |
|-------|-----------|------------------|
| **1. Input & Context Hygiene** | `PromptInjectionSanitizer` detects override phrases, wraps external text in `<<<UNTRUSTED_DATA ...>>>` delimiters | Indirect prompt injection (ASI01/ASI06) |
| **2. Scope & Blast-Radius Control** | `ScopeGuard` validates workspace-relative paths against allow/forbidden prefixes, caps file size | Path traversal, edits to `.env`, `.git/`, `.github/workflows/` |
| **3. Pre-Write AST & Secret Gate** | `ASTPolicyGate` parses code in memory; `SecretScanner` scans for keys/tokens | `eval`/`exec`/`shell=True`/SQL f-strings, secrets (AKIA, ghp_, sk-) |
| **4. Open-Source Standards Gate** | `RuffStandardsGate` runs `ruff check --select E,W,F,I,B,S` + `ruff format --check` | Style drift, Pyflakes/Bandit violations |
| **5. Commit Proving & CI/CD Gate** | `agent_quality_gate.py --staged --prove` emits `QualityProofAttestation` | Unverified code landing, missing audit trail |
### 3.1 Layer 1 – Input & Context Hygiene (`PromptInjectionSanitizer`)
- `detect(text)` runs compiled regexes (`INJECTION_PATTERNS`) against untrusted external text (issues, PRs, READMEs).
- `fence_untrusted_text(text, source)` wraps text:
```text
<<<UNTRUSTED_DATA source=github_issue_42 treat_as_data_not_instructions=true>>>
...
<<<END_UNTRUSTED_DATA>>>
```
- Ensures agent treats external text as data, never executable instructions.
### 3.2 Layer 2 – Scope & Blast-Radius Control (`ScopeGuard`)
`check(file_path, content)`:
- **SCP001** Path traversal: blocks any path containing `..`
- **SCP002** Protected paths: blocks `.git/`, `.env`, `secrets/`, `.github/workflows/`
- **SCP003** Allowlist: blocks edits outside configured `allowed_prefixes`
- **SCP004** Blast-radius cap: warns if file exceeds `max_lines_per_file` (default 800)
### 3.3 Layer 3 – Pre-Write AST & Secret Gate (`ASTPolicyGate` + `SecretScanner`)
**AST Policy Gate** — `ast.parse()` before disk write:
- **AST001** Syntax error → BLOCKING
- **AST002** `eval`/`exec`/`compile`/`__import__`
- **AST003** `os.system`/`pickle.loads`/`yaml.load`
- **AST004** `subprocess.*(..., shell=True)`
- **AST005** Bare `except:` → WARNING
- **AST006** Oversized function → WARNING
- **AST007** SQL f-string interpolation (`ast.JoinedStr` with SQL keywords)
**Secret Scanner** — per non-comment line:
- **SEC001** Private keys
- **SEC002** AWS keys (`AKIA...`)
- **SEC003** GitHub PATs (`ghp_...`)
- **SEC004** API keys (`sk-...`)
- **SEC005** Hardcoded credential assignments
### 3.4 Layer 4 – Open-Source Standards Gate (`RuffStandardsGate`)
- `ruff check --select E,W,F,I,B,S --output-format json`
  - PEP 8 (E/W), Pyflakes (F), isort (I), flake8-bugbear (B), flake8-bandit (S)
- Maps F, S, E9 → `Severity.BLOCKING`; style/lint → `WARNING`
- `ruff format --check` → Black-compatible formatting (`RUFF-FMT`)
### 3.5 Layer 5 – Commit Proving & Orchestration (`QualityControlPipeline` + CLI)
- `evaluate_files(files)` runs ScopeGuard, SecretScanner, ASTPolicyGate over `{file_path: content}`
- Computes `risk_tier` (LOW → MEDIUM → HIGH → CRITICAL), generates `audit_id` (`qc-<sha256[:12]>`)
- `report.to_agent_feedback()` formats BLOCKING findings with `file:line` + `remediation_hint` for self-healing
- CLI `--staged --prove quality_proof.json` collects staged files, runs pipeline + Ruff, hashes into `diff_sha256`, writes `QualityProofAttestation` JSON, exits non-zero on blocking findings
## 4. How Layers Block Failed Code
### 4.1 Severity Classification
- Critical security, syntax, scope, Ruff (F, S, E9) → `Severity.BLOCKING`
- Style/maintainability → `Severity.WARNING` (reported, non-blocking unless promoted)
### 4.2 In-Memory Pre-Write Blocking
- `evaluate_files()` counts `blocking_count`; if > 0, `report.passed = False`, `risk_tier` → HIGH (CRITICAL if SecretScanner triggered)
- Agent checks `if not report.passed:` before writing; feeds `to_agent_feedback()` back into prompt for self-healing
### 4.3 CLI / Pre-Commit / CI Blocking
- `main()` returns `0 if report.passed else 1`
- Exit code 1 aborts commit hook / fails CI pipeline
- Even with `--prove`, attestation records `"passed": false` and `"blocking_count": N`
## 5. SDLC Positioning
```mermaid
%%{init: {'flowchart': {'nodeSpacing': 15, 'rankSpacing': 25, 'padding': 8}}}%%
flowchart LR
  S1["1. Intake<br/>(Layer 1)"] --> S2["2. Planning<br/>(Layer 2)"] --> S3["3. Pre-Write<br/>(Layer 3)"] --> S4["4. Local/Staged<br/>(Layer 4 + 5)"] --> S5["5. CI/CD &amp; Merge<br/>(Layer 5 + pytest)"]
```
| SDLC Stage | Active Layer(s) | Trigger & Purpose |
|------------|-----------------|-------------------|
| Task Intake | Layer 1 | Fence untrusted text before agent reads it |
| Planning & File Targeting | Layer 2 | Enforce least-privilege allowed prefixes |
| Code Generation (Pre-Write) | Layer 3 | In-memory AST + secrets before disk write; self-healing feedback |
| Manual Commit / Pre-Commit | Layer 4 + 5 | `--staged --prove` enforces Ruff + emits SHA-256 attestation |
| CI/CD & PR Merge | Layer 5 + pytest | Verify `passed == True`, attestation, tests, human review |
## 6. Manual Commit Quality Proving
### 6.1 Pre-Commit Hook
`.git/hooks/pre-commit` (executable):
```bash
#!/usr/bin/env bash
python -m scripts.agent_quality_gate --staged --prove .pytest_cache/quality_proof.json
```
### 6.2 Execution Flow on `git commit`
```mermaid
%%{init: {'flowchart': {'nodeSpacing': 15, 'rankSpacing': 25, 'padding': 8}}}%%
flowchart LR
  A["git commit"] --> B["pre-commit Hook<br/>(--staged --prove)"]
  B --> C["RuffStandardsGate<br/>(F, S, E9 + Format)"]
  C --> D{"Passed?"}
  D -->|"No"| E["Write Proof (failed)<br/>Abort Commit (Exit 1)"]
  D -->|"Yes"| F["Write Proof (SHA-256)<br/>Create Commit (Exit 0)"]
```
1. **Staged File Discovery** — `git diff --cached --name-only --diff-filter=ACM`
2. **Layer 4 Validation** — `RuffStandardsGate.inspect_paths(...)`
3. **Failure & Non-Zero Exit** — any F/S/E9 → BLOCKING → `main()` returns 1
4. **Commit Aborted** — Git aborts before commit object; after fix + re-stage, commit passes and writes verified attestation
### 6.3 Team-Wide Setup
`.pre-commit-config.yaml`:
```yaml
repos:
  - repo: local
    hooks:
      - id: agent-quality-gate
        name: Agent Quality Gate
        entry: python -m scripts.agent_quality_gate --staged --prove .pytest_cache/quality_proof.json
        language: system
        pass_filenames: false
```
`pre-commit install` wires it for every developer.
## 7. Scaling Across Enterprise Dev Teams
### 7.1 Central Policy, Local Overrides
- Ship shared org-wide baseline (secrets, AST security rules, Ruff/Bandit) as versioned package or GitHub Action
- Each repo declares own `allowed_prefixes` and domain rules in `AGENTS.md` / `pyproject.toml`
### 7.2 Self-Healing Feedback Loops
- Return machine-readable `report.to_agent_feedback()` with `file:line` + `remediation_hint`
- Agent fixes own lint/AST violations before human sees PR
### 7.3 Tiered Enforcement (Audit → Warn → Block)
- Roll out new rules in advisory mode first to measure false-positive rates
- Promote high-confidence security/correctness rules to blocking
### 7.4 Runtime Cost & Blast-Radius Caps
- Pair with `TokenCircuitBreaker` (per-request/per-issue token caps), `SlidingWindowRateLimiter`, sandboxed execution (ephemeral containers/microVMs, deny-by-default egress)
## 8. Interview Q&A Cheat Sheet
**Q: Why AST inspection instead of regex?**
A: Regex misses context and produces noisy false positives. `ast.parse` deterministically catches `subprocess.run(..., shell=True)`, bare `except:`, and SQL f-strings with zero ambiguity.
**Q: How do you handle HITL without bottleneck?**
A: Automate the deterministic 80% (syntax, Ruff, SAST, secrets, scope, unit tests). Reserve human review for high-risk tiers (auth, DB migrations, payments) and Diff-vs-Intent verification.
**Q: How do you prove compliance for regulated enterprises?**
A: Every gate run emits `QualityControlReport` + `QualityProofAttestation` with `audit_id`, `diff_sha256`, `standards`, `timestamp_utc`—cryptographic proof every staged/committed change passed policy.
**Q: Why deterministic + probabilistic?**
A: Most effective pipelines pair probabilistic LLM reasoning (generation, contextual AI SAST) with deterministic enforcement (AST policies, sandboxes, strict CI/CD gates).
**Q: Benchmarks?**
A: Raw one-shot generation shows 40%–50%+ vulnerability density (OWASP Top 10 flaws) without guardrails.
## 9. Implementation Rule: Trigger-to-Gate Definition of Done
A workflow requirement is **only complete** when:
1. **Wire the Trigger** — actual entry point (`.git/hooks/pre-commit`, `.pre-commit-config.yaml`, CI workflow) created, not just CLI/library
2. **Verify End-to-End** — test the trigger itself, not only unit tests on the underlying module
3. **Document** — update `README.md` with trigger setup and usage
This rule is persisted globally as `trigger-to-gate-dod` skill (`~/.gemini/config/skills/trigger-to-gate-dod/SKILL.md`) and applies across all projects and code agents.
## 10. Verification Evidence
```bash
pytest tests/test_quality_control.py -v          # -> 9 passed in 4.18s
python -m scripts.agent_quality_gate agent/quality_control.py scripts/agent_quality_gate.py --prove .pytest_cache/quality_proof.json
# -> QUALITY_GATE_PASSED (audit_id=qc-b48da400e6e5, files=2)
```
### Artifacts
| File | Purpose |
|------|---------|
| `agent/quality_control.py` | `ASTPolicyGate`, `SecretScanner`, `PromptInjectionSanitizer`, `ScopeGuard`, `RuffStandardsGate`, `QualityControlPipeline`, `QualityProofAttestation` |
| `scripts/agent_quality_gate.py` | CLI: `--staged`, `--commit <ref>`, `--prove <path>`, `--json`, `--allow-prefix` |
| `tests/test_quality_control.py` | 9 unit tests |
| `.pre-commit-config.yaml` | Team-wide hook |
| `.git/hooks/pre-commit` | Local hook |
| `README.md` §5.h | Docs |
## 11. Lessons Learned
1. **Pre-commit wiring was initially missed** — CLI flags (`--staged`, `--prove`) were implemented but hooks weren't wired. Lesson: define requirements by *trigger*, not artifact.
2. **Unused imports** (`tempfile`, `Iterable`) caught by Ruff F401 — validates the gate itself.
3. **Trusted subprocess calls** annotated with `# noqa: S603` — demonstrates intentional, documented exceptions rather than blanket suppression.
4. **Always update README** from new code change — docs drift is a quality defect.
