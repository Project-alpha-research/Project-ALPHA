---
owner: project layer
sources:
  - packages/alpha-core/src/alpha_core/*.py
  - apps/alpha-cli/src/alpha_cli/toolbox/reserve.py
  - apps/alpha-cli/src/alpha_cli/spine/reserve.py
  - apps/alpha-cli/src/alpha_cli/toolbox/inputs.py
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

Locks it out (the code refuses reserved rows or aborts):

- RD-Agent factor loop: the worker's prepare step and funding read (`alpha_factor_data.py`) and the daily funding reader refuse rows from the date on.
  The evaluator (`rdagent_factor_eval.py`) refuses a panel receipt or factor values that reach it. The judge (`_rdagent_judge.py`) refuses a panel,
  replay or lineage matrix that reaches it. The loop is never given that data ([rules](../invariants/rdagent.md#factor-loop-and-judging)).
- RD-Agent rule families (`rdagent_rule_family.py`): the run aborts if the loader returns a bar or dividend on or after the date.
- RD-Agent journeys: the figures stop at the date and a record that reaches it is refused (`rdagent_journey.py`, `figures/rdagent_journey_figures.py`).
- RD-Agent post-verdict checks (`_rdagent_checks.py`): a replay with an exit on or after the date is refused (`RESERVED_PERIOD`).
- Rule tests (`alpha test`) and setups (`alpha setup find|study|trade`): every bar and dividend read passes the cut-off 2023-12-31 (`spine/reserve.py`).
  `spine/reserve.py` uses one boundary, core's `RESERVED_INSTANT` (the first instant of the reserved day). A row stamped at or after it is held back.
  A row stamped before it is used once it is known. A daily store read keeps it by its stamp (`CUTOFF`, one microsecond before
  the boundary). An intraday store, archive or crypto read keeps it when its interval closes by the boundary.
  Every command applies this one rule. The count of held-back bars comes from a timestamp-only scan.
  A store with held-back bars gives the label `reserved-period-held-back` and one printed sentence. A run with no held-back bars keeps its id.
  Exception: a split or dividend known only from the date on is never applied. A store that ends before 2024 but records such an action
  therefore gives other prices, and a new id, than before. Stores with no such action are byte-identical (the pinned run and find ids hold).
  A cited draft must say "held back" or "reserved period seen" when a cited run carries that label (`alpha results check`).
  Study and trade refuse an older find that used the period (`RESERVED_PERIOD_SEEN`). `alpha tool` reads a held-back run with the run's own cut-off.
- Search and score commands: `alpha optim` (grid and mcpt), `alpha validate`, `alpha backtest oos`, `run`, `portfolio` and `cross-sectional`,
  `alpha scan run`, `alpha scan hypotheses` (and `replay`), `alpha backtest run --manifest-id`, `alpha rules explain`, `alpha lookalike`, `alpha
  unusual` and `alpha labels barrier`. They use the same helper
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
  A replay of an older frozen scan is refused by its code hash, as before. `alpha monte-carlo` reads with its source run's cut-off, so it holds back
  only when the source run did.
- Research-case lane: the weekly classifier (`alpha research diagnostic weekly-classifier`), the data audit (`research_data_audit.py`), the
  run-plan controller (`research_execution.py`) and the crypto crowding and hedged-basis reads cut at the same boundary and say so. The classifier and the
  controller use `Hold`, record `reserve` and give the sentence; a plan or `--as-of` before the boundary keeps its record. The audit caps its read at
  the boundary and puts the sentence in its notes. The crypto reads drop rows stamped on or after the boundary inside the parquet scan; the count reads time
  columns only. `alpha strategy-candidate run` also caps its cut-off at the boundary. The case's sealed split (D1, D2, D3) divides only
  the data left after the cut. The reserved period is a separate, later part of the calendar that no case split can reach.
- Not built: the owner's confirmation path. It is designed, not built. It needs a new owner action type and a second build with the owner's sign-off.

Only labels it:

- Older rule runs that saw the date, and `alpha tool` on them: the label `reserved-period-seen`. Nothing is rewritten. The label is derived when the
  run is read, from its last bar date and the lack of a hold-back record (`toolbox/inputs.py`, `alpha results show`).
- A descriptive check that reads reference series published later never reads the held-back period:
  [descriptive reference reads](../invariants/cli-toolbox.md#descriptive-reference-reads).

Holds nothing back (they still read bars from the date on):

- Still to cover. Do not assume these hold anything back:
  - ML input preparation (`ml_input.py`): tied to a project's frozen export.
  - Forecast evaluation (`alpha forecast`): a forecast run is forward use; the evaluation sites need their own design.
  - `alpha propfirm`: it reads every stored bar (no cut-off).
  - `alpha scan check`: the alert watcher is forward use, so it reads the latest bars on purpose (tested:
    `test_alert_check_is_forward_use_and_still_reads_the_latest_bar`).
  - Research case registration (`research_cmds.py`): `alpha research data register` does not check a dataset's end date against the boundary. Follow-up.
    `alpha backtest holdout` is the revealed holdout itself.
  - `alpha strategy-candidate run --analysis holdout`: it reads its own sealed window as given, and that window may lie past the boundary. Owner to decide.
  - `alpha labels weights` and `importance` read a stored barrier result; one built before this change can hold events from the date on.
- Label only (display or forward use): `alpha chart`, `alpha data` reads, the assistant context.
- Exempt (forward paper use): paper trading, IBKR Paper and the daily scheduler.
- Data health (`alpha data health`, and `--check-data` on a rule test or setup) checks every stored bar, the held-back ones too.
  Its verdict can label or stop a run; its numbers do not enter a result.
- `alpha project reveal-holdout` is a separate owner-only action on a project's sealed holdout. Whether it is tied to this date: not verified.

## What the owner decided

- 2026-11-18: shortlisted factors may be confirmed once each on the reserved data. There are ten slots for the life of the reserved window, and each
  needs the owner's own yes. Approved, not built, queued behind the screens. Nothing may use a slot yet, and a stand-in user can never give the yes
  ([log](owner-decisions-5.md#2026-11-18-one-shot-confirmation-of-shortlisted-factors-on-reserved-data-approved-not-built)).
- Settled, and a different matter: only the owner reveals a project's sealed holdout ([owner authority](../invariants/research-integrity.md#owner-authority)).
  That rule is about the holdout, not about the reserved period.

## What is open

- The commands under "Still to cover": each should hold the period back or label it. Not built. Open: archived runs scored on held-back bars before
  this change are not relabelled; only rule runs derive `reserved-period-seen`. Stored hypothesis scans and backtest runs carry no last-bar
  date in a common place, so a read-only label on display needs its own design.
- Open: who may reveal the reserved period itself to rule tests or setups. This is separate from the settled holdout rule above.
