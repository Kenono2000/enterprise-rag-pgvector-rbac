---
name: prove-every-speedup
description: Enforces hypothesis-driven performance optimization inspired by Agentic Algorithm Engineering. Use whenever asked to optimize, speed up, or reduce latency/memory of code, queries, or pipelines so every change is backed by profiling, git commits, correctness checks, and repeatable before-and-after benchmarks.
---
# Prove Every Speedup (Agentic Algorithm Engineering)
Never hand-wave performance improvements. A confident explanation is not a benchmark. Every optimization must be isolated, falsifiable, verified for correctness, and proven faster by repeatable measurement.
## 1. Pre-Flight Contract (Agree Before Editing)
Before modifying any code, establish and confirm these four parameters with the user (or explicitly state them if the user provided them):
1. **Benchmark**: The exact repeatable command and representative input(s) to measure.
2. **Metric**: The target measurement (e.g., wall-clock runtime, p95 latency, throughput, peak memory, allocations).
3. **Correctness Checks**: The exact verification suite (e.g., bit-identical output diff, unit/integration tests, invariant assertions).
4. **Budget**: Maximum number of experiment loops or timebox before stopping.
## 2. The Falsifiable Hypothesis Loop
Execute optimizations one small, isolated change at a time:
1. **Profile & Predict**: Profile first to locate the bottleneck. State a falsifiable hypothesis before editing: *"This change should reduce [metric] by ~[X%] because [mechanism]."*
2. **One Small Change**: Apply a single, focused edit and commit it to Git (e.g., `git commit -m "perf: <hypothesis>"`) so it can be cleanly reverted.
3. **Verify Correctness**: Run the agreed correctness checks. If any check fails, revert immediately and record why the hypothesis failed.
4. **Benchmark & Decide**: Run the repeatable before-and-after benchmark under consistent conditions.
   - **Keep** only if measurably faster (beyond noise) AND 100% correct.
   - **Revert** immediately (`git revert` or `git reset --hard HEAD~1`) if slower, neutral, or inconclusive.
5. **Log & Iterate**: Summarize each experiment (hypothesis, predicted vs. actual impact, correctness status, kept/reverted) and repeat within the budget.
## 3. Hard Guardrails
- **No unverified claims**: Never claim a speedup until both correctness checks and benchmarks have actually run after the final edit.
- **No bundled changes**: Never combine multiple optimizations in one commit; if it's faster or breaks, you won't know which change caused it.
- **Baseline integrity**: Always measure the baseline on the same machine, input, and warm-up conditions as the candidate change.
