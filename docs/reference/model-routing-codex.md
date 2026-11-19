---
owner: delivery pipeline
sources:
  - scripts/handoff.py
  - scripts/handoff_sandbox.py
  - scripts/codex_bridge.py
  - .claude/agents/*.md
  - .codex/config.toml
  - AGENTS.md
verified: 7fb7aae6a6b242b5
---

# Model routing when Codex is turned back on

Codex has not been in use since the owner's 2026-11-19 decision
([entry](project/owner-decisions-5.md#2026-11-19-claude-agents-build-until-the-codex-subscription-returns-the-file-system-comes-first)).
This page keeps the Codex rules, so they apply again when the owner turns Codex back on. The rules in force today are
in [model routing](model-routing.md).

The original split, set on 2026-11-14:

Claude plans, decides and reviews; Codex implements. The owner chose this on 2026-11-14 ("Codex
usually has cleaner better code"; Claude is better at planning and decision making). Codex runs on
the ChatGPT Pro plan (generous, weekly limits); Claude runs on Max 5x, which is the one to ration.
`scripts/handoff.py` applies the build and review rows itself.

On this page: [Codex builds](#codex-builds), [Why these models](#why-these-models), [Calibration
builds](#calibration-builds), [What the build sandbox allows](#what-the-build-sandbox-allows), [Limits and
fallback](#limits-and-fallback).

## Codex builds

Codex, by default; [model routing](model-routing.md) gives the model, effort and time cap per task class and what stays with Claude. Run, outside any sandbox,
`uv run python scripts/handoff.py build --task docs/work/<task>/ --base main` (`python3` works too: the script needs only the standard library; small route:
`--brief <file>` with the headings Task, Decision already made, Files, Do not touch, Checks, Report). It runs Codex in a worktree, checks the diff against
policy, runs `gate.py check` and each slice's `verify` itself, drives up to two fix rounds. Read only its summary and `git diff --stat`. Exit 0 means its own
checks passed; then review (stage 04) and commit, with `03-build.json`. On a `fallback` (exit 10–13), or when the work needs the network or a decision, a
Claude sub-agent of the named model builds from the `prompt.md` it names; then run `handoff.py verify` on that worktree. Process above binds every builder.

## Why these models

Why, one line each:

- `gpt-6.2-sol` is the workhorse coding model and `gpt-6.2-astra` the frontier model for the most
  demanding work (`~/.codex/models_cache.json`); both are used at the owner's request.
- 2026-11-18: the switch to the 6.2 models was made at the owner's request. They are not yet
  calibrated on this project; every figure below was measured on `gpt-6.1-sol` or `gpt-6-astra`.
- `medium` for small tasks: calibration tasks A and B (below) came out correct and clean first time
  at `medium`; the earlier hand-run trial at `high` took 8 minutes for a task of similar size.
- `high` for standard and astra for hard: first measured 2026-11-14 (tasks F and G below),
  one build each, so still provisional.
- Lighter models (`gpt-6-luna`, "fast and affordable") are not used for building: a quiet quality
  loss costs more than the allowance saved. No evidence yet says otherwise.
- Higher efforts (`xhigh`, `max`, `ultra`) are not used by default: unmeasured, and they spend the
  weekly allowance fastest.

## Calibration builds

Calibration builds, 2026-11-14, all reviewed by Claude; model `gpt-6.1-sol` unless named, small at `medium`:

| Task | Class | Wall time | Input tokens (cached) | Output | Fix rounds | Result |
|---|---|---|---|---|---|---|
| A: redact paths in the rules-evaluate error (3 files) | small | 3m57s | 496,656 (468,736) | 3,749 | 0 | correct; an unrequested doc re-wrap (brief's fault) |
| B: aggregate the per-plan tests in `test_plan_schema.py` (1 file) | small | 2m57s | 188,778 (150,656) | 2,822 | 0 | correct, strictness kept; 314 cases to 6 |
| C: run the v2 Qlib-isolation test in a fresh process (1 file) | small | 5m03s | 156,373 (126,336) | 1,777 | 0 | correct, every assertion kept |
| D: aggregate the theme drift tests, drop a permanent skip (2 files) | small | 3m55s | 187,865 (164,864) | 3,199 | 0 | correct; 54 cases to 8 |
| E: barrier for the investigation watchdog deadline test (1 file) | small | 2m52s | 351,724 (314,112) | 2,161 | 0 | correct, test-only, assertions kept |
| F: one copy of literature acquisition code (6 files) | standard, `high` | 7m30s | 1,328,298 (1,244,160) | 19,234 | 2, empty | correct; note 1 |
| G: remove QuantPad code (28 files) | hard, `gpt-6-astra`, `high` | 20m51s | 2,796,814 (2,715,648) | 9,859 | 0 | correct; note 2 |
| H: RD-Agent model gateway and tests (3 files, `--class standard`) | standard, `high` | 19m27s | 3,228,369 (3,052,928) | 73,983 | 1 (gate) | correct; note 3 |

1. Task F's build round alone was 401,809 in and 6,010 out. Both fix rounds were spent on a brief
   check that also searched documents the builder was told not to touch (a brief error).
2. Task G was approved unchanged; the orchestrator rebuilt the SPA bundle, which needs the network.
3. The first live call found a setting 0.167.0 lacks and a CLI notice mistaken for tool use; fixed by hand.

Guarded harness files (the mutation-gate change): Claude built, Codex (0 findings) and Opus reviewed.

A fix round resumes the whole thread, so even an empty round costs about the full context again
(about 40k more input each in task F). A brief's checks must only cover files the builder may change.

Most of Codex's allowance goes on context: a turn's input count adds up what is sent with each
model call (inferred: 497k input for one turn of 32 commands, 94% cached), so every file read
early costs again on each later step; a short read list saves more than a lower effort. Re-calibrate
when a model is added, or when a class looks wrong in three builds running.
## What the build sandbox allows

Set 2026-11-18 at the owner's request (extra cache folder and pre-linked files, internet stays
off), so Codex can check more of its own work. Every round keeps `-s workspace-write`,
`approval_policy="never"`, `--ignore-user-config`, web search and the listed features off and MCP
servers stubbed; `handoff_sandbox.py` adds only:

- `sandbox_workspace_write.network_access=false`, stated (a test fails if it is ever on).
- One extra writable root (`sandbox_workspace_write.writable_roots`): a fresh uv cache per build,
  `<home>/cache/uv/<run id>`, warmed outside the sandbox before Codex starts (about 30 kB, as the
  `.venv` is already synced) and deleted when the build ends. `shell_environment_policy.set` passes
  `UV_CACHE_DIR` and `UV_OFFLINE=1`, so `uv run` works offline; if warming fails, `.venv/bin/...`.
- Read-only links to the main checkout's built web assets and frontend packages (each
  `node_modules` entry, in a real folder for tools' scratch files). Writing through a link fails
  (`EROFS`). Links go after every round, before any check or diff; a replaced link is a violation.

Codex can now run `uv run` checks (pytest, ruff, mypy, `fs.py`, `gate.py check`) and the frontend's
`node_modules/.bin` tools. It still cannot reach the network, open any socket (`TestClient` tests
hang; no localhost servers), run browsers or `tests/smoke/`, or write outside the worktree, `/tmp`
and its cache. Checks outside use the normal uv cache, never the build's.
Rejected: bypassing the sandbox (Codex reads the whole disk; with network it could send key files
away). Open gap, older than this: the worktree `.venv` is hard-linked to the user's uv cache, and
the sandbox does not stop a write through a hard link.

## Limits and fallback

Signals, as `handoff.py build` reads them (exit status in brackets):

- Codex unavailable [10]: `codex` not on PATH, `codex login status` not "Logged in", the class's model missing from the models cache, or an auth error in the
  event stream.
- Codex usage limit [11]: an `error` or `turn.failed` event (or stderr) matching "usage limit", `usageLimitExceeded`, "rate limit", "429", "quota" or
  "purchase more credits". The exact wording was read from the 0.167.0 binary, not seen live: ASSUMED until a real limit is hit.
- Codex timeout [12]: the class's time cap passed; the process group is stopped.
- Codex failed [13]: any other non-zero exit or failed turn.

On 10–13 the record's `fallback` names the Claude builder for the class. The orchestrator gives the same `prompt.md` (path in the summary) to a
general-purpose sub-agent with that model, in the same worktree, then runs `handoff.py verify --worktree <wt> --built-by claude:<model> --brief|--task ...`,
which applies the same policy and checks and writes the record with the Claude builder named. Do not wait or ask the owner. A Codex-reviewed change whose
reviewer is out goes to `reviewer` (Opus).

On a Claude limit: queue more work for Codex (several `handoff.py build` runs may go in parallel, one per worktree), keep orchestrator turns to reading
summaries and committing, and defer Opus reviews that are not on the merge path. Every fallback is recorded: the build record's `built_by` and `fallback`, and
the pull request's "Who built and who reviewed".
