---
name: getting-started-with-muse-skills
description: Baseline onboarding SOP for agent skill mechanics, frontmatter anatomy, and clipboard-based activation in conversational chat. Use when learning skill conventions, configuring playbooks, or writing custom SKILL.md templates.
category: muse
---

# Getting Started with Muse Skills

## Overview

A skill is a portable, reusable playbook: a short markdown file called `SKILL.md` that describes a capability or workflow in plain language. The format follows the open Agent Skills convention — `--- name / description / category ---` frontmatter at the top, followed by a structured body. 

Because a skill is plain text, it operates across diverse conversational AI environments and repository contexts without proprietary runtimes or runtime execution risks. Nothing to compile, nothing to install, and no arbitrary shell scripts. The skill provides the assistant with shared context and operational boundaries; the human operator remains in full control to review and approve all proposed actions.

In practical workflows, conversational agents ingest skills directly via system prompt ingestion, repository-level scanning (such as `.agent/skills/`), or clipboard-based activation in chat. This playbook defines the standard anatomy, trigger mechanics, and authoring guidelines.

## When to use

- You are new to agent skills and need an onboarding reference for how skills work.
- You want to structure and store domain-specific operational SOPs for conversational assistants.
- You are authoring a new `SKILL.md` template and want to ensure strict compliance with the Agent Skills standard.
- You want to activate a workflow playbook in an active chat session without installing complex plugins.
- You need a baseline security checklist to verify third-party agent skills before adoption.

## Core concepts

- **A skill is pure text and declarative intent.**
  `SKILL.md` consists of structured markdown with YAML frontmatter (`name`, `description`, `category`). There is no executable binary or privilege escalation. An assistant reads the directives and applies them within its existing tool permissions.
- **The five-part canonical structure:**
  Every production-grade skill follows five core sections:
  1. **Overview**: Why this capability exists and what problem it solves.
  2. **When to use**: Specific trigger phrases, situations, and operational conditions.
  3. **Core concepts**: The mental model, rules, taxonomy, and boundaries.
  4. **Practical workflow**: Step-by-step procedural guidelines and execution order.
  5. **Common pitfalls**: Anti-patterns, edge cases, and safety risks.
- **Trigger-oriented descriptions:**
  Frontmatter descriptions must clearly explain *what* the skill does and *when* it should be triggered. Routing engines and language models rely on this description to select the appropriate skill.
- **Safety and credential isolation:**
  Never hardcode API keys, passwords, database credentials, or sensitive secrets inside a skill. Skills define procedures and expectations; credentials must always remain in environment variables or secure secret managers.

## Practical workflow

1. **Locate or scaffold the skill file:**
   Create a dedicated directory under `.agent/skills/<skill-name>/` and name the file `SKILL.md`. Ensure the folder name strictly matches the `name` field in the frontmatter.

2. **Define frontmatter metadata:**
   ```yaml
   ---
   name: example-workflow-name
   description: Concise one-sentence summary of capabilities and explicit trigger conditions.
   category: development # or productivity, ai-research, utilities, etc.
   ---
   ```

3. **Author the canonical sections:**
   Populate the markdown body with concrete examples, explicit checklists, and unambiguous decision rules. Avoid vague platitudes like "write clean code" in favor of concrete heuristics like "limit cyclomatic complexity to under 10 and enforce boundary parameter validation".

4. **Activate in conversational chat:**
   - In automated IDE agents (e.g., Antigravity, Claude Code, Cursor), place the skill in the repo `.agent/skills/` directory where it is auto-discovered.
   - In manual chat sessions, paste the contents of `SKILL.md` into the conversation window with the prompt:
     > *"Please adopt the following skill playbook for our upcoming task and adhere strictly to its practical workflow."*

5. **Validate and iterate:**
   Test the skill against edge cases. When the assistant deviates from desired conventions, refine the `Core concepts` or add explicit entries under `Common pitfalls`.

## Common pitfalls

- **Overly generic triggers**: Writing descriptions like "Helps with coding" causes false activations or ignored skills. Always include specific triggers (e.g., "Use when reviewing pull requests, checking SQL migrations, or auditing diffs").
- **Monolithic skill creep**: Packing multiple distinct disciplines into a single skill. Keep skills modular and composable.
- **Executable assumptions**: Assuming the skill runner has root privileges or unvetted tools installed. Always write instructions that work across vanilla command-line or human-in-the-loop environments.
- **Credential leakage**: Pasting real access tokens or project connection strings in example sections. Always use placeholders (e.g., `<YOUR_API_KEY>`).
