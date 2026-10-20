# Mandatory Rule: Always Update Website After `README.md` or Mermaid Diagram Updates

Whenever `README.md` (either `c:\src\enterprise-rag-pgvector-rbac\README.md` or `c:\src\abyssium-studio\README.md`) is updated—including any changes to ` ```mermaid ` diagrams, architectural layers, telemetry metrics, or documentation sections—you **MUST** immediately synchronize the `abyssiumstudio.pro` React website in `c:\src\abyssium-studio`:

1. **Synchronize Mermaid Diagrams (`src/components/MermaidBlueprints.tsx`):**
   - Update `README_MERMAID_DIAGRAMS` in [`c:\src\abyssium-studio\src\components\MermaidBlueprints.tsx`](file:///c:/src/abyssium-studio/src/components/MermaidBlueprints.tsx) so all Mermaid flowcharts and sequence diagrams in `README.md` are reflected on the website with dark-mode obsidian styling (`#0f1623`, `#080c14`, `#06b6d4`, `#10b981`) and compact multi-stage layout rules (`mermaid-diagram-optimizer`).
2. **Synchronize Website Content & Components:**
   - Update corresponding components in `c:\src\abyssium-studio\src\components\` (`Hero.tsx`, `ProjectCard.tsx`, `ArchitectureDiagram.tsx`, `ExperienceTimeline.tsx`, `ContactFooter.tsx`) whenever architectural details, endpoints, test counts, or benchmarks change in `README.md`.
3. **Verify Build & Lint:**
   - Always run `npm run lint` and `npm run build` in `c:\src\abyssium-studio` after syncing to confirm zero errors.
