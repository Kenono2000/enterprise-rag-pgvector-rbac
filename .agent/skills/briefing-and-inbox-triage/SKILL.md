---
name: briefing-and-inbox-triage
description: Analyzes incoming communication, flags action items, generates structured morning/evening priority briefings, and drafts contextual responses. Use when processing high-volume emails, managing notifications, or planning daily agendas.
category: productivity
---

# Briefing and Inbox Triage

## Overview

High-volume communication channels (email, Slack, GitHub notifications, customer tickets) create continuous cognitive drag and context-switching overhead. This skill establishes an automated triage and briefing standard that sorts incoming items by true urgency, surfaces explicit action items, and prepares executive-ready daily briefings.

By decoupling scanning from decision-making, this playbook allows human operators to achieve "Inbox Zero" mentality while ensuring critical blockers, executive requests, and customer incidents are handled immediately.

## When to use

- Conducting morning priority alignment or evening wrap-up briefings.
- Processing an overflowing inbox or notification queue after time away.
- Triaging GitHub issues, pull request mentions, or project tickets into actionable batches.
- Drafting contextual, polite responses to routine status inquiries.
- Creating a clear daily focus list that separates active work from passive reading.

## Core concepts

- **The Four-Bucket Triage Model:**
  Every inbound message belongs to exactly one category:
  1. **Respond / Act Today (P0/P1)**: Blocker, time-sensitive deadline (<24h), executive escalations, system outages, direct requests from key stakeholders.
  2. **Delegate / Route (P2)**: Belongs to another team member or system; forward with clear context.
  3. **Schedule / Defer (P3)**: Important but not urgent; requires focused research, planning, or an upcoming calendar block.
  4. **Archive / Dismiss (FYI)**: Newsletters, automated build alerts (that passed), CC-only chatter, and resolved threads.

- **Action Item Extraction:**
  Never summarize a message without extracting the exact commitments. Every flagged item must identify: *Who owes what to whom, by when, and what is blocking progress.*

- **Contextual Draft Generation:**
  Draft responses must reflect the operator's voice: concise, respectful, action-oriented, and decisive. Avoid filler phrases ("I hope this email finds you well") in favor of clear confirmations or concise answers.

## Practical workflow

1. **Ingest and scan inbound items:**
   Review sender identity, subject line, urgency markers, and thread timestamps.

2. **Categorize and prioritize:**
   Assign each item into one of the four triage buckets.

3. **Format the daily briefing:**
   Generate a structured briefing document:
   ```markdown
   # Daily Operational Briefing — 2026-10-09

   ## Top Priorities (Require Action Today)
   1. **[PR #42 Approval]** OpenTelemetry Jaeger persistent storage fix waiting for merge.
      - *Action*: Run final test pass and click approve.
      - *Due*: 2:00 PM EST.
   2. **[Client Security Question]** Inquiry regarding pgvector tenant isolation and RBAC.
      - *Action*: Send technical whitepaper excerpt. Draft prepared below.

   ## Secondary & Delegated Tasks
   - [ ] Forward AWS bill audit notification to DevOps lead.
   - [ ] Schedule 30-min design review for MCP gateway expansion next Tuesday.

   ## Cleaned / Archived
   - 14 automated build notifications acknowledged and archived.
   - 3 newsletter digests moved to read-later folder.

   ---

   ### Proposed Draft Responses
   **Draft to: Security Team regarding RBAC Query**
   > "Hi David,
   >
   > Regarding the tenant isolation in our RAG stack: All vector searches enforce PostgreSQL Row-Level Security (RLS) dynamically using the user's validated JWT claims. The search filter injects `tenant_id = current_setting('app.current_tenant')` before computing cosine distance.
   >
   > Detailed architectural notes are in `docs/ENGINEERING_NOTES.md`. Let me know if you'd like a brief walkthrough.
   >
   > Best regards,
   > Ken"
   ```

4. **Operator review & dispatch:**
   The human operator reviews drafts, tweaks nuance, and dispatches responses with single-click confidence.

## Common pitfalls

- **Treating urgency as importance**: Getting sidetracked by demanding emails about minor issues while ignoring high-value strategic milestones.
- **Vague action items**: Writing "Follow up on email" instead of "Send revised pricing table to Sarah".
- **Premature sending**: Automating outbound emails without human sign-off on sensitive communications.
- **Inbox hoarding**: Leaving hundreds of read emails in the inbox rather than archiving them once actions are captured.
