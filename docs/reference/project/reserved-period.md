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
verified: 81433144d9570f50
---

# The reserved period

The reserved period is all data on or after 2024-01-01. It is kept back so that an idea is never tuned on it. Today RD-Agent's factor loop, its rule
families, its post-verdict checks and its journey figures lock it, and so do rule tests and setups. So do the commands that search or score
(listed below). Other commands label it or ignore it.

## Where the code defines the date

- `alpha_core.reserve` defines `RESERVED_DAY` and derives the ISO text `RESERVED_START`. Daily funding imports the date from core.
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
  A bar is kept only if its date is before the reserved day, for stocks and crypto alike. The count of held-back bars comes from a timestamp-only scan.
  A store with held-back bars gives the label `reserved-period-held-back` and one printed sentence. A run with no held-back bars keeps its id.
  Exception: a split or dividend known only from the date on is never applied. A store that ends before 2024 but records such an action
  therefore gives other prices, and a new id, than before. Stores with no such action are byte-identical (the pinned run and find ids hold).
  A cited draft must say "held back" or "reserved period seen" when a cited run carries that label (`alpha results check`).
  Study and trade refuse an older find that used the period (`RESERVED_PERIOD_SEEN`). `alpha tool` reads a held-back run with the run's own cut-off.
- Search and score commands: `alpha optim` (grid and mcpt), `alpha validate`, `alpha backtest oos`, `run`, `portfolio` and `cross-sectional`,
  `alpha scan run`, `alpha rules explain`, `alpha lookalike`, `alpha unusual` and `alpha labels barrier`. They use the same helper
  (`Hold` in `spine/reserve.py`) and the same cut-off, count, label and sentence as rule tests. The earlier of the cut-off and the user's own
  `--as-of` wins. A run with held-back bars records `reserve` and the label `reserved-period-held-back`, and its `research_cutoff` becomes 2023-12-31.
  A store with no bar from the date on keeps its ids and outputs, except that a split or dividend known only from the date on is never applied.
  `alpha scan check` (the alert watcher) is forward use and still reads the latest bars. Older stored runs of these commands are not rewritten and are not
  relabelled; only rule runs derive `reserved-period-seen`.
- Not built: the owner's confirmation path. It is designed, not built. It needs a new owner action type and a second build with the owner's sign-off.

Only labels it:

- Older rule runs that saw the date, and `alpha tool` on them: the label `reserved-period-seen`. Nothing is rewritten. The label is derived when the
  run is read, from its last bar date and the lack of a hold-back record (`toolbox/inputs.py`, `alpha results show`).

Holds nothing back (they still read bars from the date on):

- Still to cover: the hypothesis scan (frozen spec and the crypto lane need their own change), ML input preparation (`ml_input.py`, tied to a
  project's frozen export), forecast evaluation (`alpha forecast`; a forecast run is forward use), research diagnostics, `alpha propfirm`,
  `alpha backtest run --manifest-id` (bulk archive reads), and research case runs (`research_cmds.py`, `research_execution.py`; they also have their own
  sealed holdout, and `alpha backtest holdout` is the revealed holdout itself).
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

- The commands under "Still to cover": each should hold the period back or label it. Not built.
- Open: who may reveal the reserved period itself to rule tests or setups. This is separate from the settled holdout rule above.
