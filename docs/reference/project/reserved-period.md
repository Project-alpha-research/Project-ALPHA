---
owner: project layer
sources:
  - packages/alpha-core/src/alpha_core/*.py
  - apps/alpha-cli/src/alpha_cli/toolbox/reserve.py
  - apps/alpha-cli/src/alpha_cli/spine/reserve.py
  - apps/alpha-cli/src/alpha_cli/toolbox/inputs.py
  - apps/alpha-cli/src/alpha_cli/confirm_cmds.py
  - apps/alpha-cli/src/alpha_cli/reserved_slots.py
  - apps/alpha-cli/src/alpha_cli/spine/confirm*.py
  - packages/alpha-data/src/alpha_data/context/daily_funding.py
  - workers/rdagent/alpha_factor_data.py
  - workers/rdagent/alpha_factor_judge.py
verified: 274fe964cc5f6ccd
---

# The reserved period

The reserved period is all data on or after 2024-01-01. It is kept back so that an idea is never tuned on it. Today RD-Agent's factor loop, its rule
families, its post-verdict checks and its journey figures lock it, and so do rule tests and setups. So do most commands that search or score
(listed below); the ones that do not are under "Still to cover". Other commands label it or ignore it.

## Where the code defines the date

- `alpha_core.reserve` defines `RESERVED_DAY` and derives the ISO text `RESERVED_START` and `RESERVED_INSTANT`. Daily funding imports the date from core.
  `alpha_cli.toolbox.reserve` re-exports both names for existing CLI callers.
- The isolated RD-Agent factor runtime has no ALPHA packages. `alpha_factor_data.py` uses its `RESERVED_START` for funding checks,
  panel checks, and panel dates in the proposer prompt. A [root unit test](../../../tests/unit/test_reserved_date_one_home.py)
  checks that assignment against core and scans source for other date literals.

## What locks it, what labels it, what holds nothing back

Three kinds: the code locks it out (it refuses reserved rows or aborts), only labels it, or holds nothing back.

### Locks it out: RD-Agent

- RD-Agent factor loop: the worker's prepare step and funding read (`alpha_factor_data.py`) and the daily funding reader refuse rows from the date on.
  The evaluator (`rdagent_factor_eval.py`) refuses a panel receipt or factor values that reach it. The judge (`_rdagent_judge.py`) refuses a panel,
  replay or lineage matrix that reaches it. The loop is never given that data ([rules](../invariants/rdagent.md#factor-loop-and-judging)).
- RD-Agent rule families (`rdagent_rule_family.py`): the run aborts if the loader returns a bar or dividend on or after the date.
- RD-Agent journeys: the figures stop at the date and a record that reaches it is refused (`rdagent_journey.py`, `figures/rdagent_journey_figures.py`).
- RD-Agent post-verdict checks (`_rdagent_checks.py`): a replay with an exit on or after the date is refused (`RESERVED_PERIOD`).

### Locks it out: rule tests and setups

- Rule tests (`alpha test`) and setups (`alpha setup find|study|trade`): every bar and dividend read passes the cut-off 2023-12-31 (`spine/reserve.py`).
  `spine/reserve.py` uses one boundary, core's `RESERVED_INSTANT` (the first instant of the reserved day). A row stamped at or after it is held back.
  A row stamped before it is used once it is known. A daily store read keeps it by its stamp (`CUTOFF`, one microsecond before
  the boundary). An intraday store, archive or crypto read keeps it when its interval closes by the boundary.
  Every command applies this one rule. The count of held-back bars comes from a timestamp-only scan.
  A store with held-back bars gives the label `reserved-period-held-back` and one printed sentence.
  The identity of a test is built only from what it may read: the bars and dividends before the boundary. A later row, the held-back count, the label,
  the cut-off note, a data-health verdict and a fingerprint of the whole bar file never enter the run id, the test key, the family or a setup find id
  (`tests/unit/test_run_identity_held_back.py`). A nightly pull that only adds or revises held-back rows keeps every id, so a repeat stays one repeat.
  The manifest still describes the held-back part (`reserve.held_back_bars`). `alpha test --recheck` leaves that description out of the comparison and
  says in `identity_note` when the stored run used the older whole-file fingerprint rule; it then compares the numbers only. Stored runs are never rewritten.
  Exception: a split or dividend known only from the date on is never applied. A store that ends before 2024 but records such an action
  therefore gives other prices, and a new id, than before. Stores with no such action are byte-identical (the pinned run and find ids hold).
  A cited draft must say "held back" or "reserved period seen" when a cited run carries that label (`alpha results check`).
  Study and trade refuse an older find that used the period (`RESERVED_PERIOD_SEEN`). `alpha tool` reads a held-back run with the run's own cut-off.

### Locks it out: search and score commands

- Search and score commands: `alpha optim` (grid and mcpt), `alpha validate`, `alpha backtest oos`, `run`, `portfolio` and `cross-sectional`,
  `alpha scan run`, `alpha scan hypotheses` (and `replay`), `alpha backtest run --manifest-id`, `alpha rules explain`, `alpha lookalike`, `alpha
  unusual`, `alpha labels barrier`, `alpha research compare` and `alpha propfirm run SYMBOL`. They use the same helper
  (`Hold` in `spine/reserve.py`) and the same cut-off, count, label and sentence as rule tests. The earlier of the cut-off and the user's own
  `--as-of` wins. A run with held-back bars records `reserve` and the label `reserved-period-held-back`, and its `research_cutoff` becomes 2023-12-31.
  A store with no bar from the date on keeps its ids and outputs, except that a split or dividend known only from the date on is never applied.
  In text output the command prints the one sentence; with `--json` the result carries the `reserve` field instead, so the JSON stays one object.
  Older stored runs of these commands are not rewritten and are not relabelled; only rule runs derive `reserved-period-seen`.
  The hypothesis scan holds the period back in both lanes. A run with held-back bars puts `research_cutoff`, `reserve` and the label in its frozen spec, so
  its scan id changes; the number of hypotheses counted as tried does not. Equity bars and the split or dividend known only from the date on are never
  loaded. The crypto lane filters inside the parquet scan, so no row stamped on or after the date reaches Python; the count reads timestamps only.
  It counts every such row (bars, funding, open interest) that the user's cut-off would have admitted, so its record is `held_back_rows` and its
  sentence says "rows (bars, funding and open interest)". Other commands keep `held_back_bars` and the standard sentence. A manifest replay reads
  the whole verified artifact (its hash and overlap checks need every row) but builds no bar that closes after the boundary.
  A replay of an older frozen scan is refused by its code hash, as before. `alpha research compare` and `alpha propfirm run` print the same sentence
  and record the same `reserve` field. `propfirm` adds it to the run id only when a bar was held back, so other ids stay. `alpha propfirm --from-run`
  reads only a stored equity curve. `alpha monte-carlo` reads with its source run's cut-off, never later than 2023-12-31: a source run that recorded
  none gets 2023-12-31. `alpha labels weights` and `importance` refuse a stored barrier result that holds a bar or event from the date on
  (`RESERVED_PERIOD_SEEN`) and name `alpha labels barrier` as the next step.

### Locks it out: research cases, ML input and forecasts

- Research-case lane: the weekly classifier (`alpha research diagnostic weekly-classifier`), the data audit (`research_data_audit.py`), the
  run-plan controller (`research_execution.py`) and the crypto crowding and hedged-basis reads cut at the same boundary and say so. The classifier and
  the controller use `Hold`, record `reserve` and give the sentence (`reserve_sentence`). The audit caps its read, puts the sentence in its notes and
  records `reserve` and the label. A plan, `--as-of` or registered end before the boundary keeps its record. The crypto reads drop rows inside the
  parquet scan: Bybit rows by their stamp, Binance spot bars when they close after the boundary. `alpha strategy-candidate run` (the sandbox-only
  hedged-basis candidate of ADR-0033) cuts at 2023-12-31 by default and caps a later `--as-of`; it records `reserve` and the label. Its count reads time
  columns only, up to the user's cut-off. A new case's sealed split (D1, D2, D3) divides only the data left after the cut. An older case frozen on later
  bars fails loud on reload (its data hash or its group commitment no longer matches); its split never changes silently.
- ML input and forecast evaluation: `alpha ml export-input` (`ml_input.py`) and `alpha forecast eval` (plain and governed) use the same `Hold`,
  cut-off and sentence. A Qlib bundle with held-back bars gains `reserve.json`; with none it is unchanged. `alpha ml prepare` copies that file into
  the exchange, and `alpha ml replay` records `reserve` and the label on its run; a later replay `--as-of` is recorded as 2023-12-31.
  Labels and fold targets come from the cut panel only, so the last panel session has no label. `alpha forecast run` stays forward use: its
  manifest records `use: forward` (not part of the run id), and `alpha report` shows it; an older run shows "not recorded".
- The owner's confirmation is the one way to open the period: [below](#the-owners-confirmation).

### Only labels it

- Older rule runs that saw the date, and `alpha tool` on them: the label `reserved-period-seen`. Nothing is rewritten. The label is derived when the
  run is read, from its last bar date and the lack of a hold-back record (`toolbox/inputs.py`, `alpha results show`).
- A descriptive check that reads reference series published later never reads the held-back period:
  [descriptive reference reads](../invariants/cli-toolbox.md#descriptive-reference-reads).

### Holds nothing back

These still read bars from the date on.

- Still to cover. Do not assume these hold anything back:
  - `alpha scan check`: the alert watcher is forward use, so it reads the latest bars on purpose (tested:
    `test_alert_check_is_forward_use_and_still_reads_the_latest_bar`).
  - Research case registration (`research_cmds.py`): `alpha research data register` does not check a dataset's end date against the boundary,
    and a case approval reads the cut data without the sentence. Follow-up.
    `alpha backtest holdout` is the revealed holdout itself.
  - `alpha strategy-candidate run --analysis holdout`: it reads its own sealed window as given, and that window may lie past the boundary. Owner to decide.
- Label only (display or forward use): `alpha chart`, `alpha data` reads, the assistant context.
- Exempt (forward paper use): paper trading, IBKR Paper and the daily scheduler.
- Data health (`alpha data health`, and `--check-data` on a rule test or setup) checks every stored bar, the held-back ones too.
  Its verdict can label or stop a run; its numbers do not enter a result, and neither its verdict nor its fingerprint enters an identity.
- `alpha project reveal-holdout` is a separate owner-only action on a project's sealed holdout. Whether it is tied to this date: not verified.

## The owner's confirmation

`alpha confirm plan|run|list|show` ([card](../../../research/tools/reserved-confirmation.md)) is the final check. The rules, enforced in
code and by the store:

- What: one frozen rule test. That is a stored `alpha test` run made with the period held back: its spec hash, test key (spec, asset,
  store, dates, data content), costs and engine settings (seed, quick, diagnostics). Nothing can change. Setup Lab runs: not yet.
- Who: the owner asks for it in chat, by idea name; Claude shows `plan`, then runs `alpha confirm run` in the terminal. There is no
  confirmation step and no Touch ID ([decision](owner-decisions-6.md#2026-11-22-no-touch-id-for-the-final-check-claude-runs-it-on-request)).
  MCP, web routes, the generic web launcher, the nightly run, RD-Agent, follow and the toolbox cannot reach it (tested).
- `run` prints the plan first: what is tested, the slots used and left, every earlier confirmation, whether the code changed,
  and that the slot cannot be given back. Then it spends.
- Span: from the first stored bar on or after 2024-01-01 to the last stored bar when the slot is spent. It is frozen in the
  receipt, so a later bar is never read (bars added afterwards are left out; the stamps up to it must still match).
- Recheck first: the earlier period is computed again (`spine/recheck.py`). It must match the stored run; only the count of
  held-back bars may differ. A mismatch spends nothing.
- Receipt before read: a slot receipt (slot, test key, family, run, spec hash, frozen test, time) is written in one
  `BEGIN IMMEDIATE` transaction before any reserved bar is read. Then the frozen test is read again; its hash must equal the
  receipt's. A crash after the receipt resumes with the same slot and the same span.
- Ten slots, ever: slot 1 to 10, one receipt per test key, per run and per rule on one asset (the deflation family on that
  asset). The store's UNIQUE and CHECK constraints refuse a duplicate or an eleventh slot; two processes cannot both take the last.
- The read: only `reserve.open_with_receipt`, which reads the receipt and checks the asset and the frozen bars on every call.
  Only `spine/confirm_run.py` calls it. The structural guard lists it under its own kind, `receipt:`. It scores the frozen rule
  only, and the same rule at double costs: no parameter neighbours are run on the reserved bars (they would show which tuning did
  best there). `alpha follow start` refuses the confirmation run.
- The result: the same reading, scored on reserved bars only (the rule warms up on the bars just before 2024), beside the
  earlier reading. It is stored as a run labelled `reserved-period-confirmation`, shown whatever it is, and never
  discarded. Tools refuse that run. Its ledger kind is `reserved_confirmation`: not a research trial, and outside every
  family count used to deflate another test. Its own deflation uses the family count as it stood.
- The family label: after a confirmation, every later `alpha test` of the same rule on the same asset carries
  `reserved-period-confirmed-in-family` (tuned settings are new test keys but the same idea), and cannot be confirmed.
  The family is the rule kind on one symbol, so all owner rules on one symbol are one family. Not covered: the same idea
  on a similar asset (SPY, then VOO), or rewritten as another rule kind. `plan` lists every earlier confirmation, so a
  near-duplicate is seen before a slot is spent; no similarity is computed. `alpha next` shows the slots.
- Limits: any process on this computer that runs `alpha confirm run` spends a slot. The rows are plain, unsigned rows: whoever
  can write the control store can change them. The reserved bars are in store files the same OS user can read. This guards
  the research pipeline, not the files.

## What the owner decided

- 2026-11-18: shortlisted factors may be confirmed once each on the reserved data. There are ten slots for the life of the reserved window, and each
  needs the owner's own yes. A stand-in user can never give the yes
  ([log](owner-decisions-5.md#2026-11-18-one-shot-confirmation-of-shortlisted-factors-on-reserved-data-approved-not-built)).
  2026-11-21: built for rule tests as [above](#the-owners-confirmation), each idea once, ten slots.
  2026-11-22: no Touch ID and no confirmation step; Claude runs the final check when the owner asks in chat
  ([log](owner-decisions-6.md#2026-11-22-no-touch-id-for-the-final-check-claude-runs-it-on-request)).
- Settled, and a different matter: only the owner reveals a project's sealed holdout ([owner authority](../invariants/research-integrity.md#owner-authority)).
  That rule is about the holdout, not about the reserved period.

## What is open

- The commands under "Still to cover": each should hold the period back or label it. Not built. Open: archived runs scored on held-back bars before
  this change are not relabelled; only rule runs derive `reserved-period-seen`. Stored hypothesis scans and backtest runs carry no last-bar
  date in a common place, so a read-only label on display needs its own design.
- Only the owner's request opens the period, one frozen rule test at a time ([above](#the-owners-confirmation)). Setup Lab runs and
  RD-Agent factors cannot be confirmed yet.
- Guard: [a structural test](../../../tests/unit/test_research_reads_are_cut.py) checks every `load_bars`, `load_dividends` and `read_bars` call.
  Its `as_of` must come from the reserve (`reserve.CUTOFF`, a `Hold`'s `as_of`, or a helper parameter that every caller fills so). Every other
  read is listed as `exempt:` (forward use, display, verification) or `open:` (a known leak, with the change that fixes it). A new unlisted read
  fails, and so does a stale entry. A polars read of a bars store file is allowed only where listed. It does not see other readers (for example
  `PointInTimeSource`, the crypto bulk artifacts) or callers outside the package; its docstring lists these limits.
