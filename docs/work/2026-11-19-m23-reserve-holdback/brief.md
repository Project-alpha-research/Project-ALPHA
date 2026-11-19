# Brief: Rule tests and Setup Lab hold back the reserved period

Task: Make `alpha test` and `alpha setup find|study|trade` read only bars dated before `alpha_core.reserve.RESERVED_DAY` (2024-01-01), say so in one plain sentence, and label older runs that saw the period. The owner-only confirmation path is designed here. It ships as a second build.

Workspace: `apps/alpha-cli/CONTEXT.md`. Read these rows: research integrity › Owner authority (always); engineering › Hash-bound source bytes (always); `cli-runs.md` (rule tests, tools); toolbox component page. Also read `docs/reference/project/reserved-period.md`.

Decision: [2026-11-19 All features work together as one system; four approvals, item (2)](docs/reference/project/owner-decisions-6.md#2026-11-19-all-features-work-together-as-one-system-four-approvals). Related: [2026-11-18 one-shot confirmation of shortlisted factors](docs/reference/project/owner-decisions-5.md#2026-11-18-one-shot-confirmation-of-shortlisted-factors-on-reserved-data-approved-not-built).

## Findings (file:line)
- **Rule test.** `spine/run.py` (436 lines, far below the 1,500 limit) loads bars and dividends with no cut-off at :135-136. The test period comes only from the bars. `assemble_run_spec` :72-104 sets warm-up = `spec.min_train` and folds over everything that remains. The run identity payload is built at :147-162 and already has `"research_cutoff": None` at :152. `idea_id` is at :38. The deflation test key is `spine_test_key(spec, symbol, first_ts, last_ts, ppy)` at :238-240. The test id is the SHA of the spec plus the sorted run ids, at :394. `write_validation_run` is called without `as_of` at :277, so `manifest["research_cutoff"]` is None (`validate_cmds.py:340`). The period names full_history / tradable / scored come from the bars passed to `spine/diagnose.py:300-302`. diagnose never reloads bars.
- **Loader.** `_runner.load_bars(as_of=…)` (`_runner.py:217-283`) cuts bars after `as_of` and applies only corporate actions known by then. Its default is the year 2999 (:253). `load_dividends` (:286-315) works the same way. `run_identity_for` is at :717-765. `source_fingerprint` (:646-688) hashes every bar and dividend that a run consumes.
- **Setups.** `spine/setup_find.py:153` loads all bars in `_asset`. The find id is the SHA of the spec plus `asset=source_fingerprint` keys plus context (:323-327, :334-346). Study and trade do not load bars themselves. Both reach `study_inputs` (:270-302) through `checked_study_inputs` (`setup_study.py:267`, `setup_trade.py:276`). `study_inputs` reloads at :291 and refuses `DATA_CHANGED_SINCE_FIND` when the fingerprint differs. Edge behaviour today:
  - A signal on the last bar is rejected with `no-next-bar` (`alpha_study/setup/evaluate.py:75`).
  - A horizon past the last bar gives `complete=False` with no return (`setup_study.py:62-80`).
  - A trade still open at the end is marked at `bars[-1].close`, reason `open-at-end` (`setup_exits.py:160`).
- **RD-Agent.** `_rdagent_judge.py` raises `DataError("panel reaches reserved window")` at :224-225 and "replay reaches reserved window" at :722-723 and :970-971. The replay at :970 also requires `days[-1] + 2 days < RESERVED_DAY`, so decision, fill and exit all fall before the date. It filters with `date < RESERVED_DAY` (:385). The toolbox only labels: `reserved-period-seen` (`toolbox/inputs.py:51-54`, :96-97, applied at `toolbox/runner.py:114`).
- **owner_auth.py.** It offers WebAuthn `verify_action_assertion` (:321) and `local_confirmation_options` / `verify_local_confirmation` (:421-509). Every action type is bound to a research case:
  - `action_binding` needs a `project_id` and a case revision (:244-286).
  - `derive_action_artifact_hash` accepts only `sc_`/`rc_` ids (:87-129).
  - The types are a closed `Literal` / `OWNER_ACTION_TYPES` (`control_store.py:135-152`, :477-496), with SQL `CHECK` lists at `_control_schema.py:592` and :723.
  - The guard hook blocks agent tools from `/owner-auth` and `owner-auth enroll|recover` (`scripts/claude_hooks.py:33`, :95-108).
  - ADR-0038 notes that a local click can be confirmed by any local process (`claude_hooks.py:31`).
- **One-shot precedent.** `control_store.reveal_holdout` (:11728) refuses a second reveal ("was already revealed"). Its actor is free text (`project_cmds.py:649-667`) and it is protected only by deny rules in `.claude/settings.json`.
- **Ledger.** `spine/ledger.py:38-75` is append-only. `trial_record._spine` (:75-150) knows only `rule_test`, `setup_find`, `setup_study`, `setup_trade` and `tool:*`; any other kind becomes "other" and is not counted. Families are `spine:{rule}` and `setup:<idea>`, so a shorter period does not split a family.
- **Labels.** `results_cmds.py:190` shows `manifest.spine.labels`. The Workstation explanations are `LABELS` in `alpha_web/_setup_runs.py:41-70` (setup runs). The draft-check phrases are in `spine/check.py:16-25`.

## Rules
1. **Cut-off.** `C = datetime.combine(RESERVED_DAY - 1 day, 23:59:59, UTC)`. Every rule-test and setup bar and dividend read passes `as_of=C`. A bar is kept if and only if `bar.ts.date() < RESERVED_DAY`. This is the same rule for stocks and crypto, and the same test the RD-Agent judge uses (:385). Splits and dividends that become known after C are not applied.
2. **Count without reading.** The held-back count N is the number of stored bar timestamps `>= RESERVED_DAY`. It comes from a timestamp-only scan; no OHLCV value is read. If N > 0 the run gets the label `reserved-period-held-back` and prints exactly one sentence: "Held back N bars from 2024-01-01 on; they are kept for the owner's confirmation of an idea, so this test did not use them."
3. **Boundary.** Warm-up and indicators use kept bars only. A decision on the close of the last kept bar has no t+1 bar, so there is no fill (rule tests: engine end of data; setups: `no-next-bar`).
   - A position still open on the last kept bar is never closed at a held-back price. It keeps today's end-of-data treatment: a setup trade is marked at the last kept close with reason `open-at-end`.
   - A study horizon that crosses the date is `complete=False` and has no return (existing `pending-at-end`).
4. **Identity.** Put `research_cutoff="2023-12-31"` into the identity payload (`run.py:152`) and pass `as_of="2023-12-31"` to `write_validation_run` only when N > 0. With N = 0 the run id stays the same byte for byte.
   - For setups, the source fingerprint already changes when bars are cut. The find manifest also records `reserve: {reserved_start, held_back_bars}`.
   - Monte Carlo then reloads the same bars, because it reads `research_cutoff` (`monte_carlo_cmds.py:444-450`).
5. **Old runs are never rewritten.** A rule run whose `data_period.last_ts >= RESERVED_DAY` and that has no `reserve` block is shown with `reserved-period-seen`. The label is derived when the run is read. Old ledger rows stay as they are; read-time labelling uses their `last_ts`.
6. **Old finds that saw the period.** Study and trade on such a find (any asset `last_bar >= RESERVED_DAY` and no `reserve` block) are refused before any bar is loaded. Code `RESERVED_PERIOD_SEEN`. Message: "This find used data from 2024-01-01 on, which is now held back." Hint: "Run alpha setup find again; the new find holds that data back."
7. **Counting.** A held-back rerun of an old spec has a new `last_ts`, so it is a new test in the same family (+1 trial). Nothing resets or reduces a count.
8. **Tools.** `toolbox/inputs.py` `load_run` loads bars and dividends with `as_of` = the run's `research_cutoff` (when set). Today dividends are loaded with no cut-off (:209), which would make every held-back run fail with `RUN_DATA_CHANGED`.
9. **Confirmation (build 2; designed now).**
   - The owner confirms one test id or one find id with a new action type, `confirm_reserved_period`. It needs a WebAuthn assertion (Touch ID). Local click is refused for this type.
   - Artifact hash = SHA-256 of the canonical `{kind, test_or_find_id, spec_sha256, assets, reserved_start}`.
   - `alpha test --confirm-reserved <test_id>` only consumes a receipt. It cannot create one. MCP has no tool for this. The hook already blocks `/owner-auth`. A stand-in answer is not a receipt.
   - One receipt per id. A second run for the same id or the same `spec_sha256` is refused: "Already confirmed on <date>; a second look is not a fresh confirmation."
   - A spec that any earlier ledger row ran with `last_ts >= RESERVED_DAY` is refused (see owner question 2).
   - The run uses the frozen spec, no diagnose variants and no re-fit. It runs once, continuously, over all bars. It reports "earlier period" (must reproduce the original run's scored numbers exactly, otherwise refuse) and "held-back period" (equity from the open of the first held-back bar). Trades carried across the date are listed separately.
   - Ledger: kind `confirmation` in the same family, `counts_for_deflation=True`, with `confirmed_test_id`, `receipt_id`, `confirmed_by="owner"`, `confirmed_at`, `reason` and `reserved_start`.

## Change (build 1, about 550 lines)
- New `apps/alpha-cli/src/alpha_cli/spine/reserve.py` (about 70 lines): `CUTOFF`, `held_back_count(resolved)` (`pl.scan_parquet(...).select("ts")`), `record(n)`, `sentence(n)`, `seen(last_ts, manifest) -> bool`.
- `spine/run.py` :135-165, :277, :288-312: pass `as_of`, record `reserve`, add the label, print the sentence, set the conditional `research_cutoff`.
- `spine/setup_find.py` :153, :291: pass `as_of`, record `reserve`, add the label, refuse per Rule 6.
- `setup_study.py` and `setup_trade.py`: carry the find's held-back label and sentence only.
- `toolbox/inputs.py:206-209`: apply Rule 8.
- `results_cmds.py`: derive the label per Rule 5 and print the plain sentence.
- `spine/check.py` `LABEL_PHRASES`: add both labels.
- `alpha_web/_setup_runs.py` `LABELS`:
  - `reserved-period-held-back`: "Data from 2024-01-01 on was held back for the owner's confirmation."
  - `reserved-period-seen`: "This run used data from 2024-01-01 on, before that data was held back. It is not a fresh test on that period."
- Docs: `reserved-period.md` (move rule tests and setups to "locks it out", then re-verify) and `cli-runs.md`.
- New test file `tests/unit/test_reserve_holdback.py`. Fully typed. Floats use `pytest.approx(rel=1e-9, abs=1e-12)`.

## Do not touch
- `packages/alpha-research/src`, `packages/alpha-validation/src`, `tests/bias_guards`, `tests/oracles`, `.claude/`, `.agents/`, `.github/`, `scripts/` (the hook already covers `/owner-auth`), `CLAUDE.md`, `AGENTS.md`.
- `owner_auth.py`, `control_store.py`, `_control_schema.py`: no changes in build 1.
- Build 2 must change `owner_auth.py` with owner sign-off:
  - Add a branch in `derive_action_artifact_hash` and in `action_binding` that skips the research-case revision for `confirm_reserved_period`.
  - Refuse that type in `local_confirmation_options` / `verify_local_confirmation`.
  - Add the type to `OwnerActionType` and `OWNER_ACTION_TYPES` (schema v8 migration of both `CHECK` lists).
- Do not edit `_rdagent_judge.py`.

## Done when
- **Guard test (in `test_reserve_holdback.py`).**
  - Stock store `seed_store(n=1600)`: 2020-01-01 to 2024-05-19. Crypto `BTC/USD` with 365 bars a year.
  - Poison every bar on or after 2024-01-01 (prices ×1000, still valid).
  - Wrap `_runner.load_bars` and `load_dividends` and record the latest returned timestamp.
  - For `run_idea`, `run_find`, `run_study`, `run_trade` and toolbox `load_run`: no returned bar has `ts.date() >= RESERVED_DAY`. The results and the run id equal those from a store cut at 2023-12-31, except for the recorded N.
  - The ledger `last_ts` is before the date. The sentence and the label are present.
- **Rule 6 refusal test.** Write a find manifest without `reserve` and with `last_bar` = 2024-02-01.
- **Byte proof, files left unedited.**
  - `uv run pytest -q tests/unit/test_spine_honesty_3.py tests/unit/test_setup_trade.py`: run id `3d7c42078dd76b34` (:370), find id `32d1f3b953038de2` and trades SHA `b865b7dc…` (:371-376) stay the same.
  - All `seed_store` fixtures end by 2021 (largest n is 700, starting 2020-01-01). `test_setup_known_on.py` (2026 bars) does not call the spine.
- **Commands.**
  - `uv run pytest -q tests/unit -k "reserve or spine or setup or toolbox or results"`
  - `uv run lint-imports`
  - `uv run pytest -q tests/bias_guards`
  - `uv run python scripts/fs.py stale`
  - `uv run python scripts/gate.py check --base origin/main`

## Follow-ups (point 3)
All of these read the same bars with no reserve. Each follow-up should hold back by default or add a label.
- **Cover first:**
  - `alpha optimise`: `optim_cmds.py:118`, :372. It searches parameters, so it leaks the most.
  - `alpha validate`: `validate_cmds.py:141`, :147.
  - `alpha backtest`: `backtest_cmds.py:107`, :278, :400.
  - lookalike / unusual: `lookalike_cmds.py:45`.
  - labels: `labels_cmds.py:163`.
  - research diagnostics: `research_diagnostic_cmds.py:197`.
  - ML input: `ml_input.py:86`.
  - hypothesis scan: `_hypothesis_scan.py:281`.
  - scan: `scan_cmds.py:134`.
  - rules: `rules_cmds.py:157`.
  - cross-sectional and portfolio: `_cross_sectional.py:71`, `_portfolio.py:141`.
  - forecast: `forecast_cmds.py:97`, :277, :512.
  - prop firm: `_propfirm.py:118`.
  - `research_cmds.py:3200` and `research_execution.py:202`, :297. Research cases also have their own sealed holdout.
- **Label only (display or forward use):** `chart_cmds.py:549`, `data_cmds.py:597`, `assistant_context.py:53`, :176.
- **Exempt (forward paper use):** `_paper.py:168`, `_ibkr_paper.py:555`, `daily_scheduler.py:339`.
- **Already locked:** `rdagent_rule_family.py:107`.
- **Covered in build 1:** toolbox comparison (`inputs.py:275`, uses `as_of=last`), diagnose, and Monte Carlo (through Rule 4).

## Owner questions
1. Should stocks and crypto use the same date? Recommend yes: one `RESERVED_DAY` with one home. A 2023-12-31 crypto bar is kept, the same as in RD-Agent.
2. Can an idea already tested on 2024 or later data ever be confirmed? Recommend no. Refuse when any ledger row with the same `spec_sha256` has `last_ts >= 2024-01-01`. The owner may approve a new spec, but the record shows the link through `idea_id`.
3. Should rule and setup confirmations share the ten-slot budget from 2026-11-18? Recommend yes: it is the same reserved window. One budget, counted in the one ledger.

## Report
Give:
- The changed line count per file.
- The byte proof (the three pinned values unchanged).
- The guard-test names, and the latest timestamp each path returned.
- N for the two fixtures.
- Confirmation that no protected path and `owner_auth.py` were not touched.
- `fs.py stale` output after re-verifying `reserved-period.md`.

### Critical Files for Implementation
- /home/hunta/alpha-clean-base/Project-ALPHA/apps/alpha-cli/src/alpha_cli/spine/run.py
- /home/hunta/alpha-clean-base/Project-ALPHA/apps/alpha-cli/src/alpha_cli/spine/setup_find.py
- /home/hunta/alpha-clean-base/Project-ALPHA/apps/alpha-cli/src/alpha_cli/_runner.py
- /home/hunta/alpha-clean-base/Project-ALPHA/apps/alpha-cli/src/alpha_cli/toolbox/inputs.py
- /home/hunta/alpha-clean-base/Project-ALPHA/apps/alpha-cli/src/alpha_cli/owner_auth.py (build 2 only)