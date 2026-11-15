# RD-Agent loop: a usable fake route, resume, and exact call accounting

**Status:** Scoped
**Rough size:** M

## Problem / why

The live failure-path tests of 2026-11-15 found:

- **The fake chat route cannot drive a loop.**
  - It refuses `temperature` unless `--accept-unhonoured temperature` is given.
  - It answers `{"fake": true, ...}`, which fails RD-Agent's response schema, so RD-Agent gives
    up after two calls.
  - So no free, offline end-to-end loop test exists. Cap and cancel tests had to spend real
    Codex calls.
- **No resume.** The launcher refuses an existing run directory, and RD-Agent's own checkpoint
  resume is not exposed. A run killed in loop 2 of 3 must start again from scratch.
- **Call counts disagree after a cancel.** The gateway's budget counted 4 calls, but its call
  log (and so `calls-labelled.jsonl`) has 3: a call in flight when the run was stopped is
  counted but never logged.
- **The receipt shows the wrong cap.** It printed `run_max_calls: 60` for a run started with
  `--run-max-calls 4`, although the cap of 4 was enforced.

## What "done" looks like

- A `scripted` chat route that replays recorded, schema-valid RD-Agent replies (or builds them
  from RD-Agent's own schemas). A CI-runnable test then drives one full loop with no model and
  no cost.
- `factor_loop_launch.py resume --run-dir ...` continues from RD-Agent's last checkpoint with the
  same panel and ledger, and records the resume in the receipt.
- The gateway logs a call record (status `cancelled`) for every call it counted. The receipt
  shows the run's own cap.

## Dependencies

[RD-Agent factor loop supervision](rdagent-factor-loop-supervision.md) covers the job-supervisor
part; this item covers testing and recovery.

## Sources

- Runs `2026-11-15-systest-cap2` (fake route), `2026-11-15-systest-codex-cap` (cap of 4 hit:
  4 x 200 then 2 x 429 `budget_exhausted`) and `2026-11-15-systest-cancel` (SIGTERM, clean stop).
