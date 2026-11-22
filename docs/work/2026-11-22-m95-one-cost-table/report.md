# Report: one cost table (m95)

## Answer

The RD-Agent judge now reads fee and slippage from `ROWS["crypto_spot"]` in `spine/cost_classes.py`. The native daily rule study keeps its
numbers: its file is hash-bound for daily approvals and may not import the table (`test_daily_guard_boundary`). A test holds them equal.
The judge keeps no cost number of its own. A change of the row reaches its next score.

## Call sites

| Site | Old numbers | New source |
|---|---|---|
| `_rdagent_judge.py` (`FEE_BPS`, `SLIPPAGE_BPS`; replay, gap replay, spread cost) | fee 10, slippage 6 | table row `crypto_spot`: fee 10, slippage 5 (`_rdagent_costs.judge_costs()`, read at each call) |
| `_native_daily_rule_study.py` (`daily_rule_terms_proposal`) | fee 10, slippage 5 | kept in the bound file; a test holds them equal to the row |
| `research_cmds.py` (~line 3135, 1 and 2 bp) | flat 1 and 2 | NOT changed: old research-case lane, scheduled for deletion |

## Decisions

1. The judge scores a panel of spot coins from the Binance store, so its class is `crypto_spot` (constant `JUDGE_COST_CLASS`).
2. A new judge trial stores `costs` = fee, slippage, `source: class-default`, `asset_class`. The evaluation record repeats it in `disclosures.costs`
   and the configuration hash covers it. Old stored trials are not touched; one without `costs` counts as "other costs".
3. The judge feedback adds one sentence when earlier trials used other costs: "N earlier scores were made under other costs than these. They keep
   their own costs, are not re-scored, and still count as trials." Repeats are not counted.
4. Slippage 6 to 5 is the real change: new judge scores cost 1 bp less per side. The judge's own byte pins were re-run under the old row (fixture
   `pre_table_costs`) and still match, so cost is the only difference. `test_fractional_turnover_and_cost_are_weighted` now expects 15 bp (10 + 5).
   `test_rdagent_gapped_universe` golden uses 1.0005. `test_known_only_evaluation_bytes_match_declared_primary_baseline` has a new hash: that
   run fails before any replay, so only the costs record and cost text are new.
5. Spread (`spread_bps_full` 2.0) of the daily study is not in the table: left as is.

## Not done (protected)

`workers/rdagent/alpha_factor_judge.py` lines 59 and 518 still say "10 bps fee plus 6 bps slippage" in prompt text. The brief forbids edits to
`workers/**` and to prompts. The text is now stale by 1 bp. `tests/unit/test_rdagent_factor_judge.py:473` pins the "6 bps" string. The owner should
decide on that edit.

## Tests

Fail-first: `tests/unit/test_rdagent_judge_costs.py` failed at import before the change (no `_rdagent_costs`). It covers: crypto row used; a US ETF
row read by class; a table change reaches the judge and the study; an old stored score is not altered and is counted. `alpha test` golden pins
(`test_cost_classes*`) pass unchanged.

Failing before my change on main too (not mine): `test_rdagent_funding_columns::test_freeze_legacy_bytes_and_optional_receipt`,
`test_rdagent_model_gateway::test_codex_confinement`. Three `test_native_daily_rule_lifecycle` tests error in this sandbox
(they need `scripts/run_owned_test.py`).

## Docs

`docs/reference/invariants/cli-cost-classes.md` (new section "Other readers of the table") and `rdagent.md` (one sentence). ADR-0049/0050 are
decision records and keep their dated text. No baseline entry in `.claude/code-size-baseline.json` asked to change.
