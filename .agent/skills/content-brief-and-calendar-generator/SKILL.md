---
name: content-brief-and-calendar-generator
description: Generates strategic content briefs, editorial calendars, audience targeting profiles, and multi-channel promotional roadmaps. Use when planning technical blogs, product launches, documentation rollouts, or marketing sprints.
category: business-marketing
---

# Content Brief and Calendar Generator

## Overview

High-impact technical and business content fails when it lacks clear search intent, defined reader personas, or a structured editorial distribution plan. Publishing ad-hoc articles without a cohesive publishing rhythm produces scattered messaging, low discoverability, and poor audience retention.

This skill automates the creation of comprehensive content briefs and multi-week editorial calendars. It bridges the gap between high-level engineering milestones or product announcements and polished, audience-aligned publications across technical blogs, social channels, and documentation hubs.

## When to use

- Planning technical blog posts, engineering deep-dives, or architecture breakdowns.
- Building a multi-week editorial calendar for product launches or open-source releases.
- Defining audience personas, target search intents, and primary value propositions before drafting.
- Repurposing engineering documentation into developer relations (DevRel) content.
- Aligning marketing, developer advocacy, and core engineering teams on publishing roadmaps.

## Core concepts

- **The Anatomy of a Technical Content Brief:**
  A complete brief must define:
  1. **Working Title & Core Hook**: A compelling, benefit-driven headline.
  2. **Target Persona & Skill Level**: Who is reading (e.g., Senior Platform Engineers, SecOps leads) and their existing knowledge baseline.
  3. **Primary Search Intent & Keywords**: The specific technical problem the reader is querying in search engines.
  4. **Core Thesis & Key Takeaways**: The non-negotiable mental shift or actionable insight the reader must gain.
  5. **Code & Architecture Requirements**: Specific repos, diagrams, or benchmarks that must be embedded.
  6. **Call to Action (CTA)**: Next steps (e.g., star repo, join Discord, run Docker quickstart).

- **Editorial Calendar Cadence:**
  Balancing content formats across a 4-week sprint:
  - *Hero Content (P0)*: In-depth architecture guides, benchmark reports, or major feature deep dives.
  - *Hub Content (P1)*: Practical tutorials, how-to guides, and troubleshooting recipes.
  - *Spoke / Micro Content (P2)*: Quick tips, benchmark snippets, and social summary threads directing traffic to hero content.

## Practical workflow

1. **Conduct thematic and keyword discovery:**
   Identify current user questions, frequently encountered repo issues, or newly shipped features (e.g., "Distributed Tracing in Enterprise RAG with Jaeger").

2. **Generate the structured content brief:**
   ```markdown
   # Content Brief: Zero-Downtime Distributed Tracing for Enterprise RAG

   ## Metadata
   - **Target Persona**: Staff MLOps and Backend Engineers.
   - **Primary Search Intent**: "OpenTelemetry distributed tracing FastAPI Streamlit pgvector".
   - **Difficulty Level**: Advanced.
   - **Target Word Count**: 1,800 - 2,200 words.

   ## Narrative Outline
   1. **The RAG Black Box Problem**: Why logs fail when queries cross Streamlit, FastAPI, and async pgvector.
   2. **OTel Semantic Conventions**: Setting up spans across HTTP, gRPC, and LLM calls.
   3. **Persistent Jaeger Storage**: Replacing ephemeral memory with Badger volumes.
   4. **Step-by-Step Walkthrough**: Real code excerpts from `app/observability.py`.
   5. **Benchmark & Results**: Trace latency overhead (<2ms) and real trace visualization.

   ## Embedded Assets Required
   - Architecture sequence diagram (Mermaid).
   - Link to GitHub repository branch `feature/issues-15-16-17-hardening`.
   ```

3. **Map into a multi-week editorial schedule:**
   Organize briefs into an actionable calendar table specifying publish date, channel, author, and review status.

4. **Multi-channel derivative planning:**
   Extract 3 social micro-posts, an email newsletter teaser, and documentation updates for every published long-form post.

## Common pitfalls

- **Writing without an explicit persona**: Producing content that is too simple for senior engineers and too cryptic for beginners.
- **Ignoring visual and code assets**: Delivering walls of abstract text without architectural diagrams, terminal outputs, or runnable code snippets.
- **Publishing in isolation**: Releasing a blog post without updating corresponding repo READMEs or sharing on community channels.
- **Unrealistic publishing cadence**: Committing to daily deep-dive posts and abandoning the calendar due to burnout.
