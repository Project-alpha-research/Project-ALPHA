---
owner: project layer
sources:
  - packages/alpha-core/src/alpha_core/*.py
  - apps/alpha-cli/src/alpha_cli/toolbox/reserve.py
  - apps/alpha-cli/src/alpha_cli/toolbox/inputs.py
  - packages/alpha-data/src/alpha_data/context/daily_funding.py
  - workers/rdagent/alpha_factor_data.py
  - workers/rdagent/alpha_factor_judge.py
verified: 589c83cc8dc12538
---

# The reserved period

The reserved period is all data on or after 2024-01-01. It is kept back so that an idea is never tuned on it. Today only
RD-Agent's factor loop truly locks it. Other commands label it or ignore it.

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
  replay or lineage matrix that reaches it. The loop is never given that data ([rules](../invariants/workers.md#rd-agent-worker)).
- RD-Agent rule families (`rdagent_rule_family.py`): the run aborts if the loader returns a bar or dividend on or after the date.
- RD-Agent journeys: the figures stop at the date and a record that reaches it is refused (`rdagent_journey.py`, `figures/rdagent_journey_figures.py`).

Only labels it:

- `alpha tool` (the [toolbox](components/toolbox.md)): a run whose data used the date gets the label `reserved-period-seen`. Nothing is hidden, and a
  cut-off for tool inputs is not built (`toolbox/inputs.py`).

Holds nothing back:

- `alpha test` (rule tests) and `alpha setup`, according to [ideas and things considered](ideas-and-considered.md#open-questions). A search of
  `test_cmds.py` and `setup_cmds.py` finds no use of the date or of `reserve.py`; the code they call was not traced. Not verified further.
- Every other command: not verified.
- `alpha project reveal-holdout` is a separate owner-only action on a project's sealed holdout. Whether it is tied to this date: not verified.

## What the owner decided

- 2026-11-18: shortlisted factors may be confirmed once each on the reserved data. There are ten slots for the life of the reserved window, and each
  needs the owner's own yes. Approved, not built, queued behind the screens. Nothing may use a slot yet, and a stand-in user can never give the yes
  ([log](owner-decisions-5.md#2026-11-18-one-shot-confirmation-of-shortlisted-factors-on-reserved-data-approved-not-built)).
- Only the owner reveals a holdout ([owner authority](../invariants/research-integrity.md#owner-authority)).

## What is open

- The reserve policy for rule tests and setups: one held-back period for everything, a held-back tail chosen per idea, or the status quo with
  labels. Who may reveal it is also open ([open questions](ideas-and-considered.md#open-questions)).
