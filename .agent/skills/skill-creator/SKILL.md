---
name: skill-creator
description: Scaffolds, validates, and refines custom agent skills into standardized Agent Skills format (YAML frontmatter + trigger design + guardrails). Use when creating new skills, converting procedures into playbooks, or improving existing skill triggers.
category: workflow-automation
---

# Skill Creator

## Overview

A good skill is a **reusable playbook**: the distilled judgment of an expert, written so an agent or human operator can execute complex workflows reliably without reinventing the approach each time. Ineffective skills are vague advice ("write clean code" or "make it fast"); high-impact skills are specific, triggerable, and safe — specifying what to do, when to do it, how to do it step-by-step, and what pitfalls to avoid.

This meta-skill provides the complete engineering process for designing, structuring, testing, and hardening new skills conforming to the Agent Skills standard.

## When to use

- Turning a repeated manual workflow or engineering SOP into an autonomous agent skill.
- Authoring a bespoke skill for team repositories or agent platforms.
- Reviewing, refactoring, or hardening draft skills before publishing them to a catalog.
- Splitting monolithic, oversized skills into composable, single-responsibility units.
- Optimizing YAML frontmatter descriptions to ensure accurate routing and trigger precision.

## Core concepts

- **Trigger-first design:**
  A skill that never triggers is dead weight. Begin with the operational trigger: What exact prompt, keyword, or system condition should activate this playbook? Formulate the frontmatter description as:
  `"[Core capability summary]. Use when [explicit trigger condition 1], [trigger condition 2], or [trigger condition 3]."`
- **Specificity over broad generalizations:**
  "Web development" is an entire discipline; "Building reactive data dashboards with Streamlit and OpenTelemetry instrumentation" is an actionable skill. Restrict the scope to deep, repeatable directives.
- **The five canonical sections:**
  1. `Overview`: Architectural rationale and capability boundaries.
  2. `When to use`: Explicit activation triggers and exclusion criteria.
  3. `Core concepts`: Architectural principles, mental models, rules, and taxonomies.
  4. `Practical workflow`: Numbered, deterministic execution steps and configuration templates.
  5. `Common pitfalls`: Anti-patterns, edge cases, failure recovery, and safety warnings.
- **Executable examples:**
  Abstract prose leads to hallucination or variable outputs. Concrete code snippets, configuration blocks, and CLI patterns anchor the model's behavior.
- **Safety by construction:**
  Skills must strictly avoid destructive defaults (unconditional `rm -rf`, unconstrained database drops, credential harvesting, or unvetted external downloads).

## Practical workflow

1. **Scope and name the skill:**
   Select a lowercase, hyphen-separated identifier matching the directory name:
   `my-custom-skill` located at `.agent/skills/my-custom-skill/SKILL.md`.

2. **Draft the YAML frontmatter:**
   ```yaml
   ---
   name: my-custom-skill
   description: Concise capability summary. Use when triggering conditions arise.
   category: development # or productivity, ai-research, utilities, etc.
   ---
   ```

3. **Flesh out the five sections:**
   - Write an unambiguous `Overview` defining what the skill solves.
   - List at least 4-5 bulleted operational scenarios in `When to use`.
   - Document domain invariants and mental models in `Core concepts`.
   - Provide sequential, actionable steps in `Practical workflow`.
   - Highlight high-frequency failure modes and edge cases in `Common pitfalls`.

4. **Verify trigger sensitivity:**
   Test simulated prompts against the skill's description to ensure it activates when intended and ignores unrelated queries.

5. **Lint and format:**
   Ensure clean Markdown formatting, proper code fence languages, valid YAML headers, and no broken internal links or placeholders.

## Common pitfalls

- **Vague descriptions**: Descriptions lacking operational verbs and triggers prevent discovery by routing agents.
- **Hardcoded environments**: Hardcoding machine-specific absolute file paths or ephemeral ports that break on other machines.
- **Missing negative boundaries**: Forgetting to specify what the skill should *not* do (e.g., failing to state "Do NOT run drop database commands without explicit confirmation").
- **Overloading**: Trying to make one skill handle database migration, UI design, and customer support all at once.
