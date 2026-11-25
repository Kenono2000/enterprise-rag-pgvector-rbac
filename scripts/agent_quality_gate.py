"""
scripts/agent_quality_gate.py
-----------------------------
CI/CD & manual-commit CLI runner for `agent.quality_control`.
Supports inspecting explicit paths, `--staged` git changes, or `--commit <ref>`,
and emits a verifiable `QualityProofAttestation` with `--prove <path>`.
"""

from __future__ import annotations

import argparse
import hashlib
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from agent.quality_control import (
    QualityControlPipeline,
    QualityProofAttestation,
    RuffStandardsGate,
    ScopeGuard,
)


def collect_files(paths: List[str]) -> Dict[str, str]:
    collected: Dict[str, str] = {}
    for raw in paths:
        p = Path(raw)
        if p.is_file():
            collected[p.as_posix()] = p.read_text(encoding="utf-8", errors="replace")
        elif p.is_dir():
            for child in p.rglob("*.py"):
                if ".venv" in child.parts or "__pycache__" in child.parts:
                    continue
                collected[child.as_posix()] = child.read_text(encoding="utf-8", errors="replace")
    return collected


def git_changed_files(staged: bool = False, commit: str | None = None) -> List[str]:
    if staged:
        cmd = ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM"]
    elif commit:
        cmd = ["git", "diff-tree", "--no-commit-id", "--name-only", "-r", commit]
    else:
        return []
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)  # noqa: S603
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run AI Code Agent & Manual Commit Quality Control Gate.")
    parser.add_argument("paths", nargs="*", help="Files or directories to inspect.")
    parser.add_argument("--staged", action="store_true", help="Inspect git staged changes for manual commit proving.")
    parser.add_argument("--commit", default=None, help="Inspect files changed in a specific git commit.")
    parser.add_argument("--allow-prefix", action="append", default=[], help="Restrict edits to allowed path prefixes.")
    parser.add_argument("--no-ruff", action="store_true", help="Skip Ruff PEP 8/format standards check.")
    parser.add_argument("--prove", default=None, help="Write verifiable QualityProofAttestation JSON to this path.")
    parser.add_argument("--json", action="store_true", help="Emit JSON report.")
    args = parser.parse_args(argv)

    target_paths = list(args.paths)
    if args.staged or args.commit:
        target_paths.extend(git_changed_files(staged=args.staged, commit=args.commit))

    if not target_paths:
        print("No target files specified or staged.")
        return 0

    files = collect_files(target_paths)
    scope = ScopeGuard(allowed_prefixes=args.allow_prefix or None)
    pipeline = QualityControlPipeline(scope_guard=scope)
    report = pipeline.evaluate_files(files)

    if not args.no_ruff:
        ruff_findings = RuffStandardsGate().inspect_paths(list(files.keys()))
        report.findings.extend(ruff_findings)
        report.blocking_count = sum(1 for f in report.findings if f.severity.value == "blocking")
        report.warning_count = sum(1 for f in report.findings if f.severity.value == "warning")
        report.passed = report.blocking_count == 0

    if args.prove:
        diff_hash = hashlib.sha256(
            "".join(f"{k}:{v}" for k, v in sorted(files.items())).encode("utf-8")
        ).hexdigest()
        proof = QualityProofAttestation(
            audit_id=report.audit_id,
            passed=report.passed,
            risk_tier=report.risk_tier,
            target_ref="staged" if args.staged else (args.commit or "workspace"),
            diff_sha256=diff_hash,
            checked_files=report.checked_files,
            blocking_count=report.blocking_count,
            warning_count=report.warning_count,
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
        )
        Path(args.prove).write_text(proof.model_dump_json(indent=2), encoding="utf-8")

    if args.json:
        print(report.model_dump_json(indent=2))
    else:
        print(report.to_agent_feedback())

    return 0 if report.passed else 1


if __name__ == "__main__":
    sys.exit(main())
