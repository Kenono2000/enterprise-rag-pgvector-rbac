---
name: regex-and-cron-utility
description: Designs, parses, validates, and optimizes regular expressions and cron scheduling expressions with human-readable breakdowns and edge case testing. Use when building regex filters, scheduling automated tasks, or debugging cron schedules.
category: utilities
---

# Regex and Cron Utility

## Overview

Regular expressions (regex) and cron expressions are ubiquitous across backend automation, data ingestion pipelines, log parsing, and scheduling engines. However, both syntaxes are notoriously prone to subtle bugs: catastrophic backtracking (ReDoS) in regex, off-by-one errors in calendar cron fields, and silent timezone mismatches.

This skill provides an automated engineering utility for generating, explaining, testing, and optimizing regular expressions and cron schedules. It guarantees human-readable breakdowns, explicit edge case validation matrices, and engine-specific dialect compatibility (POSIX, PCRE, Python `re`, standard 5-field cron vs. Quartz/AWS 6-field cron).

## When to use

- Generating complex regex patterns for data extraction (URLs, emails, IP addresses, log tokens).
- Diagnosing and optimizing slow or vulnerable regex expressions prone to ReDoS.
- Designing cron expressions for automated batch jobs, database backups, or cache invalidation.
- Translating ambiguous human scheduling requests (e.g., "every other Tuesday at 3:15 AM") into exact cron syntax.
- Converting cron schedules between 5-field UNIX and 6-field AWS/Quartz syntaxes.

## Core concepts

- **Cron Expression Anatomy (Standard 5-Field UNIX):**
  ```text
  ┌───────────── minute (0 - 59)
  │ ┌───────────── hour (0 - 23)
  │ │ ┌───────────── day of month (1 - 31)
  │ │ │ ┌───────────── month (1 - 12 or JAN - DEC)
  │ │ │ │ ┌───────────── day of week (0 - 6 or SUN - SAT; 0 or 7 is usually Sunday)
  │ │ │ │ │
  * * * * *
  ```
  *Special Characters*:
  - `*`: Every interval.
  - `,`: Value list separator (`1,15,30`).
  - `-`: Range of values (`9-17`).
  - `/`: Step values (`*/15` = every 15 minutes).

- **AWS / Quartz 6-Field Variance:**
  AWS CloudWatch and Quartz use 6 or 7 fields: `minute hour day-of-month month day-of-week year`. They also require `?` (no specific value) when either day-of-month or day-of-week is specified to avoid conflict.

- **Regex Safety & ReDoS Prevention:**
  Never use nested unbounded quantifiers like `(a+)+` or `([a-zA-Z]+)*` against untrusted inputs. Exponential backtracking can freeze event loops and cause denial of service. Always prefer atomic groups, possessive quantifiers, or strictly bounded character classes.

## Practical workflow

1. **Input specification & dialect verification:**
   Specify the exact engine:
   - For Regex: Python `re`, JavaScript ECMAScript, Go `regexp`, or PCRE.
   - For Cron: UNIX crontab, GitHub Actions, AWS EventBridge, or Kubernetes CronJob.

2. **Cron generation and human explanation:**
   Provide the exact expression followed by the human translation and next 5 run executions.
   ```text
   Expression: 15 3 1,15 * *
   Explanation: "At 03:15 on day 1 and 15 of every month"
   Timezone: UTC
   Upcoming 5 Executions (assuming reference date 2026-10-09):
   1. 2026-10-15 03:15:00 UTC
   2. 2026-11-01 03:15:00 UTC
   3. 2026-11-15 03:15:00 UTC
   4. 2026-12-01 03:15:00 UTC
   5. 2026-12-15 03:15:00 UTC
   ```

3. **Regex generation and test matrix:**
   Provide the pattern, named capture groups, and an explicit match/non-match test table:
   ```regex
   Pattern: ^(?P<year>\d{4})-(?P<month>0[1-9]|1[0-2])-(?P<day>0[1-9]|[12]\d|3[01])$
   ```
   ```markdown
   | Test Input | Expected | Match Groups | Notes |
   | :--- | :--- | :--- | :--- |
   | `2026-10-09` | MATCH | year: 2026, month: 10, day: 09 | Valid ISO date |
   | `2026-13-01` | NO MATCH | - | Month 13 out of range |
   | `2026-00-15` | NO MATCH | - | Month 00 out of range |
   | `2026-10-32` | NO MATCH | - | Day 32 out of range |
   ```

## Common pitfalls

- **Day-of-Month vs. Day-of-Week intersection in UNIX cron**: In standard UNIX crontab, if both day-of-month and day-of-week are set to non-`*` values, they operate as an **OR** condition, not an **AND** condition.
- **Timezone omissions**: Writing a cron job without specifying whether the scheduler runs in local server time, UTC, or user timezone.
- **Overly greedy regex**: Using `.*` instead of non-greedy `.*?` or specific delimiters, leading to unintended capture across line breaks.
- **ReDoS vulnerability**: Deploying unbenchmarked complex regexes on untrusted user-submitted text fields.
