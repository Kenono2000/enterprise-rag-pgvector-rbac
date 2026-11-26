---
name: ui-minimal-whitespace
description: Enforces minimal whitespace compaction across all UI/UX coding (CSS, React, HTML, Tailwind). ALWAYS active whenever designing, building, or refactoring web UIs, layouts, cards, headers, or footers to maximize information density, scannability, and readability without excessive vertical or horizontal padding.
---
# UI/UX Minimal Whitespace Compaction

When designing, building, or refactoring any web UI (CSS, Tailwind, React, HTML), always keep vertical and horizontal whitespace to a minimum while preserving crisp visual hierarchy and readability.

## Core Rules
- **Header & Navigation**: Keep sticky headers compact (`padding: 0.5rem–0.65rem 1.25rem`). Avoid oversized banners or multi-row chrome.
- **Section Rhythm**: Use tight section padding (`1.75rem–2.25rem 0` instead of `4rem–6rem`) and compact section headers (`margin-bottom: 1rem–1.25rem`).
- **Hero Sections**: Keep hero padding compact (`1.75rem–2.25rem 0`), tighten headline-to-subtitle-to-CTA spacing (`0.5rem–1.25rem`), and avoid tall empty margins above the fold.
- **Cards & Panels**: Use compact card padding (`1rem–1.25rem`) and tight vertical gaps (`0.75rem–1rem`) between stacked cards or list items.
- **Grids & Strips**: Use compact interior padding (`0.75rem–1rem`) and tight gaps (`0.5rem–1rem`) for stat strips, tag lists, and detail grids.
- **Footers**: Keep footer padding minimal (`1.5rem–2rem 0 1rem`) with compact contact cards.
- **Readability Guardrail**: Never sacrifice contrast, touch target usability, or `:focus-visible` accessibility rings when compacting whitespace.
