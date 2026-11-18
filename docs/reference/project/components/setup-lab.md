---
owner: project layer
sources:
  - apps/alpha-cli/src/alpha_cli/setup_cmds.py
  - apps/alpha-web/src/alpha_web/api/setup_runs.py
  - apps/alpha-web/frontend/src/panels/SetupLabPanel.tsx
  - packages/alpha-study/src/alpha_study/setup/**/*.py
verified: ace952b390858ffe
---

# Setup Lab

Setup Lab is golden path 2: the owner describes a chart setup ("a double bottom", "a pullback in an
uptrend") and sees every past match, and then what happened after, before any trading rule is fixed. It has
three commands and one Workstation screen.

## Why it exists

Many of the owner's ideas are chart setups, not machine-learning models, and the owner wants them judged by
the same ledger and statistics as RD-Agent's ideas
([design brief](../owner-decisions-2.md#2026-11-14-the-retail-traders-fit-is-the-design-brief)). Looking at
the matches first, with the outcome hidden, keeps the owner from fitting a rule to what happened next. The
work order that put it first is in [volume 4](../owner-decisions-4.md#2026-11-18-working-order-golden-paths-1-and-2-reach-the-screen-first).

## Its job in the research loop

Steps 1 to 4 of the [research loop](../overview.md#the-research-loop) for a chart setup: state the idea,
look at it, measure it, then trade it with declared exits. It is a way of working, not a strategy.

## Intended design

- A setup is a small TOML spec: a name, assets, a daily timeframe, ordered filters, an optional trigger and
  named reference levels. Expressions read only bars already seen
  ([setup causality](../../invariants/study.md#setup-causality)).
- `alpha setup find <spec>` records every match and counts separate occurrences (days within ten bars of
  each other are one). It draws contact sheets that stop at the entry open: nothing after entry is computed
  or drawn until the outcome is asked for.
- `alpha setup study <find_id>` measures net forward returns after each occurrence against drift and
  against random dates, with one counted exploratory trial, a figure and citable facts.
- `alpha setup trade <find_id>` trades the occurrences long or short with declared exits (stop, target, time),
  after per-asset costs, in percent and in risk units of the initial stop (R). The opposite direction on the
  same entries is an uncounted control.
- The Workstation screen (Research → Setup Lab) only reads stored results through
  `GET /api/setup/runs`. It shows the data health finding beside each non-pass result. Older runs read “Data health: not recorded.”

## What is real today

All three commands run; each has a smoke test, and on 2026-11-17 a double-bottom spec ran on stored SPY and
BTC/USDT daily bars as a system test, not evidence of an edge. The screen exists and is read-only. Not built:
sizing, the owner's setup library and the daily scan with export, and starting a find from the screen. See the
capabilities on [STATUS.md](../../../../STATUS.md) and the tool cards for [find](../../../../research/tools/setup-find.md),
[study](../../../../research/tools/setup-study.md) and [trade](../../../../research/tools/setup-trade.md).

## Where it lives

- **Workspaces:** none (code sits in `apps/alpha-cli`, `apps/alpha-web` and `packages/alpha-study`, owned by
  [command line](command-line.md), [Workstation](web-workstation.md) and [strategies and signals](strategies-and-signals.md)).
- **Capabilities:** `setup-find`, `setup-study`, `setup-trade`
- Code: `apps/alpha-cli/src/alpha_cli/setup_cmds.py`, `apps/alpha-cli/src/alpha_cli/spine/setup_find.py`,
  `packages/alpha-study/src/alpha_study/setup/`, `apps/alpha-web/src/alpha_web/api/setup_runs.py`,
  `apps/alpha-web/frontend/src/panels/SetupLabPanel.tsx`.
- Tests: `tests/unit/test_setup_find.py`, `test_setup_study.py`, `test_setup_trade.py`,
  `test_web_setup_runs.py`; smoke checks `tests/smoke/test_setup_*_smoke.py`.
- How to change it: [apps/alpha-cli/CONTEXT.md](../../../../apps/alpha-cli/CONTEXT.md) and
  [apps/alpha-web/CONTEXT.md](../../../../apps/alpha-web/CONTEXT.md).
- **Plan:** the [three golden paths](../../../roadmap/production-scope.md#the-three-golden-paths) in the checklist.

## Decisions and open questions

- Decided 2026-11-18 (orchestrator's order, reversible; see the [decisions log](../owner-decisions.md), volume 4): Setup Lab comes first.
- Open: the reserve policy for setups. Today a setup run holds nothing back
  ([ideas and things considered](../ideas-and-considered.md#open-questions)).

## Never

- Never show or compute anything after the entry open in a find; outcomes appear only in study and trade.
- Never let an expression read a bar it could not yet have seen.
- Never present a setup result as evidence of an edge; it is one counted look.
- The rules: [study invariants](../../invariants/study.md) and [CLI runs](../../invariants/cli-runs.md).
