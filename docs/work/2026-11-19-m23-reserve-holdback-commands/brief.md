# Brief: More commands hold back the reserved period

Task: Make the commands that search or score read only bars dated before `alpha_core.reserve.RESERVED_DAY`. Use the same helper and the same rule as build 1 (`spine/reserve.py`). Stop at a clean boundary inside about 700 changed lines and list what is left.

Workspace: root `CONTEXT.md`, then `apps/alpha-cli/CONTEXT.md` (always rows), `docs/reference/project/reserved-period.md`, and the earlier brief `docs/work/2026-11-19-m23-reserve-holdback/brief.md` (section "Follow-ups (point 3)") and its `report.md`.

Decision: [2026-11-19 All features work together as one system; four approvals, item (2)](../../reference/project/owner-decisions-6.md#2026-11-19-all-features-work-together-as-one-system-four-approvals).

## Order
1 optimise, 2 validate, 3 backtest, 4 hypothesis scan and scan, 5 rules, 6 cross-sectional and portfolio, 7 lookalike and unusual, 8 labels, 9 ML input, 10 forecast evaluation, 11 research diagnostics.

## Rules
- Bars, dividends and other series load with the cut-off 2023-12-31. A bar is kept only if its date is before the reserved day. A split or dividend known only from that day on is not applied.
- With held-back bars the command prints the one sentence and records the label `reserved-period-held-back` where it records labels.
- Identity changes only when bars were held back. With none held back, ids and outputs stay as they were.
- Old stored results are never rewritten.

## Exempt
Paper trading, the daily scheduler, chart and data display, and research-case lanes with their own sealed holdout (`research_cmds.py`, `research_execution.py`). Do not edit `_rdagent_judge.py`.

## Do not touch
`packages/alpha-research/src`, `packages/alpha-validation/src`, `tests/bias_guards`, `tests/oracles`, golden files, `.semgrep/`, `.github/`, `.claude/`, `.agents/`, `scripts/`, `uv.lock`, `CLAUDE.md`, `AGENTS.md`, `owner_auth.py`, `control_store.py`, `_control_schema.py`, `_rdagent_judge.py`.

## Done when
- A poisoned store (bars from the date on times 1000, a 2024 split and dividend) gives the same result as a store cut at the date, for each covered command, and a wrapped loader never returns a bar, dividend or split dated on or after the date.
- The pinned tests stay unedited and green.
- `uv run lint-imports`, `tests/bias_guards`, `fs.py stale` and `gate.py check --base origin/main` pass.
