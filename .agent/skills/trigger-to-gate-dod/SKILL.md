---
name: trigger-to-gate-dod
description: Mandatory global Definition of Done (DoD) for all code agents. Always wire and verify the end-to-end workflow trigger (e.g., pre-commit hooks, CI workflows, cron/schedules, API routes), not just the underlying CLI or library.
---
# Global Rule: Trigger-to-Gate Definition of Done (DoD)
Whenever a task requests a workflow, quality gate, automation, or lifecycle check (e.g., "manual commit quality proving", "CI check", "scheduled job"):
1. **Wire the Trigger**: Never stop at implementing the library or CLI flags. Always create and wire the actual entry-point trigger (e.g., `.git/hooks/pre-commit`, `.pre-commit-config.yaml`, `.github/workflows/*.yml`, or entrypoint registration).
2. **Verify End-to-End**: Test the trigger/entry point itself, not only unit tests on the underlying module.
3. **Document**: Update the project's `README.md` (or primary docs) with the trigger setup and usage.
