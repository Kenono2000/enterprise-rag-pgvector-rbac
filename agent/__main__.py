"""
CLI entrypoint for the Tri-Paradigm Autonomous SDLC Runtime
(LangGraph State Machine + CrewAI Role Orchestrator + Hermes Agent Skill Synthesizer).

Usage:
    python -m agent                         # Show status, CrewAI specs & Hermes skills
    python -m agent status                  # Show status, CrewAI specs & Hermes skills
    python -m agent recall "<query>"        # Recall matching Hermes SKILL.md playbooks
    python -m agent crew "<title>" [desc]   # Kick off CrewAI SDLC crew (Architect/Auditor/Triager)
    python -m agent synthesize "<title>"    # Synthesize a Hermes SKILL.md & ShareGPT trajectory
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

from agent.workflow import (
    HermesSkillSynthesizer,
    PatchProposal,
    SDLCCrewOrchestrator,
    parse_github_webhook,
)


def run_cli(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="hermes",
        description="Enterprise Zero-Trust RAG — Hermes Agent + CrewAI + LangGraph SDLC CLI",
    )
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("status", help="Display CrewAI roles, LangGraph topology, and Hermes skills")

    recall_p = subparsers.add_parser("recall", help="Recall matching Hermes Agent SKILL.md playbooks")
    recall_p.add_argument("query", nargs="+", help="Search query keywords")
    recall_p.add_argument("--max-skills", type=int, default=3, help="Maximum skills to recall")

    crew_p = subparsers.add_parser("crew", help="Kick off the CrewAI SDLC 3-agent crew")
    crew_p.add_argument("title", help="Issue or task title")
    crew_p.add_argument("description", nargs="?", default="", help="Optional issue description")

    synth_p = subparsers.add_parser("synthesize", help="Preview Hermes SKILL.md & ShareGPT RL synthesis")
    synth_p.add_argument("title", help="Issue or task title")
    synth_p.add_argument("--persist", action="store_true", help="Write SKILL.md to .agent/skills/")

    args = parser.parse_args(argv)
    sandbox_root = Path.cwd().resolve()

    if args.command in (None, "status"):
        crew_bundle = SDLCCrewOrchestrator.build_crewai_crew("Status Check")
        skills_dir = sandbox_root / ".agent" / "skills"
        all_skills = sorted(p.parent.name for p in skills_dir.glob("*/SKILL.md")) if skills_dir.exists() else []
        hermes_skills = [s for s in all_skills if s.startswith("hermes-")]
        payload = {
            "service": "Hermes + CrewAI + LangGraph Autonomous SDLC CLI",
            "workspace": str(sandbox_root),
            "crewai_runtime": crew_bundle["runtime"],
            "crew_agents": [
                {
                    "name": a["name"],
                    "role": a["role"],
                    "model_tier": a["model_tier"],
                }
                for a in crew_bundle["agents"]
            ],
            "discovered_skills_count": len(all_skills),
            "hermes_synthesized_skills": hermes_skills,
            "commands": [
                "hermes status",
                'hermes recall "<query>"',
                'hermes crew "<issue_title>" ["<description>"]',
                'hermes synthesize "<issue_title>" [--persist]',
            ],
        }
        print(json.dumps(payload, indent=2))
        return 0

    if args.command == "recall":
        query_str = " ".join(args.query)
        matched = HermesSkillSynthesizer.recall_relevant_skills(
            sandbox_root, query_str, max_skills=args.max_skills
        )
        print(
            json.dumps(
                {
                    "query": query_str,
                    "matched_count": len(matched),
                    "skills": matched,
                },
                indent=2,
            )
        )
        return 0

    if args.command == "crew":
        result = SDLCCrewOrchestrator.kickoff_crew(args.title, args.description)
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "synthesize":
        event = parse_github_webhook(
            {
                "issue": {"number": 1, "title": args.title, "body": f"Synthesize skill for {args.title}"},
                "repository": {"full_name": "Kenono2000/enterprise-rag-pgvector-rbac"},
            }
        )
        sample_patches = [
            PatchProposal(file_path="agent/workflow.py", content="# Verified SDLC patch\n")
        ]
        skill = HermesSkillSynthesizer.synthesize_skill(
            event=event,
            patches=sample_patches,
            judge_verdict={"score": 1.0},
            triage_summary={"concise_summary": "All offline pytest checks passed."},
            sandbox_root=sandbox_root,
            persist=args.persist,
        )
        trajectory = HermesSkillSynthesizer.export_rl_trajectory(
            event=event,
            branch=f"feature/{event.issue_id}",
            patches=sample_patches,
            judge_verdict={"score": 1.0},
            triage_summary={"concise_summary": "All offline pytest checks passed."},
            repairs_used=0,
        )
        print(
            json.dumps(
                {
                    "hermes_skill": skill.model_dump(),
                    "sharegpt_trajectory": trajectory.model_dump(),
                },
                indent=2,
            )
        )
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(run_cli())
