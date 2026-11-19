# RD-Agent worker: the current page

This page says what the RD-Agent worker does today, how to launch it, how to propose and discuss ideas, and what must not change. The dated
change notes, the pinned probe and the older fixtures are in [CHANGE-NOTES.md](CHANGE-NOTES.md); nothing was deleted, only moved there.
The routing page is [CONTEXT.md](CONTEXT.md).

On this page: [What the loop does today](#what-the-loop-does-today), [How to launch](#how-to-launch),
[Judging rules](#judging-rules), [Propose and discuss](#propose-and-discuss), [Where things live](#where-things-live),
[Moved from the project page](#moved-from-the-project-page). The judging rules and the proposal pause have their own pages.

## What the loop does today

RD-Agent's own factor loop (`rdagent.app.qlib_rd_loop.factor`, unmodified) runs with ALPHA as the judge
([ADR-0049](../../docs/adr/0049-alpha-judges-rdagent-factors.md)). RD-Agent proposes and codes factors. The runner sends each factor's values to
`alpha_cli.rdagent_factor_eval`, which runs in ALPHA's environment as a subprocess. The worker imports no ALPHA package.

- Each factor declares `declared_direction: +1` or `-1`, `primary_clock: weekly` or `monthly`, and `direction_reason`. A missing declaration is refused before coding.
- Decision days start at 2021-01-01; outcomes run from the next open to the next open. Other clocks and the opposite sign are diagnostics and cannot pass.
- The screen is a rank-IC test against the many-tries correction. A passing clock must then show that the top third beats the bottom third before costs;
  if not it is `SPREAD_FAIL`. It is then replayed with costs of 10 bps fee plus 6 bps slippage per side, and deflated.
- `CANDIDATE` passed the screen, spread, replay and deflation. It is a lead for one owner-approved check on reserved data, never evidence by itself.
  `DEFLATION_FAIL` passed the first three but not deflation. All results are exploratory, not admitted.
- RD-Agent never sees data on or after 2024-01-01 ([reserved period](../../docs/reference/project/reserved-period.md)).
- A run is at most 3 loops and 60 model calls. The full rule text, with every dated change, is in
  [CHANGE-NOTES.md](CHANGE-NOTES.md#alpha-judged-factor-loop-2026-11-14).
- The data is a frozen universe file; missing days and delisted names are allowed with explicit disclosure, the data
  is not survivorship-free, and renamed or split tickers need an owner-supplied break list.
- Human-authored rule families (written by a person, frozen and hash-checked before the run) are backtested on
  [Nautilus](../../docs/reference/project/components/nautilus.md) without any 2024 data and go into the same trial
  ledger, so they count toward how many ideas were tried, but never mix into RD-Agent's factor statistics or the
  summary it proposes from (`alpha_cli.rdagent_rule_family`).

## How to launch

One command starts and watches a run. Copy `research/examples/rdagent.example.toml` to `rdagent.toml`, set the paths, then:

```sh
bash scripts/setup_rdagent.sh --with-factor-runtime      # once; hash-pinned Python 3.11 runtime
alpha rdagent run --dry-run     # shows what would start, then the exact command; starts nothing
alpha rdagent run               # starts the launcher below; prints the run folder
alpha rdagent status            # working, waiting for you, finished or stopped; the next command
```

The config holds only the path of the key file. The command never reads or prints the file.
It passes no new argument: RD-Agent reads the same inputs and is judged the same way.

What it runs (the launcher line, written out):

```sh
export ALPHA_RDAGENT_SOURCE=... ALPHA_FACTOR_PYTHON=...   # as printed by the setup script
.venv/bin/python workers/rdagent/factor_loop_launch.py run \
  --data-dir /abs/alpha/data --run-dir /abs/runs/<date>-<slug> \
  --gateway-data-dir /abs/runs/model-gateway-state \
  --trial-ledger /abs/runs/rdagent-trial-ledger/rdagent-factor-trials.jsonl \
  --run-id <id> --loop-n 2      # at most 3 loops and 60 model calls; Codex and Ollama routes
  # optional: --universe /abs/workers/rdagent/universes/binance-spot-liquid.json
  #           --family-switch-after 3 --api-timeout 180 --provider-retries 1
```

- `factor-requirements.lock`: 79 hash-pinned packages (the stock runtime's plus pandas 2.2.3,
  tables, pyarrow, pandarallel, fire, scipy); recorded by
  `install_stock_profile.py --profile factor`. `gate.py doctor` names it when missing.
- `factor_loop_entry.py`: verifies the source pin, imports RD-Agent through a meta-path finder
  (the source root is never on `sys.path`) and runs the loop.
- `alpha_factor_data.py`: writes RD-Agent's `daily_pv.h5` folders and the truncated copies the
  prefix-invariance (look-ahead) check uses.
- The run folder holds `panel/` (frozen panel and receipt), `factor_data/`, `work/` (RD-Agent's
  own log and workspaces), `evaluations/` and `evaluations.jsonl` (one ALPHA record per
  iteration), `feedback.jsonl` (the model's suggestion beside ALPHA's decision), `launch.jsonl`,
  `logs/` and `receipt.json`. The trial ledger is shared by all runs and append-only.
- Generated factor code runs with the gateway's address and token removed from its environment.

## Judging rules

The full text is in [judge-rules.md](judge-rules.md).

- **Shortlist bookkeeping.** Every evaluation factor and ledger row records `shortlist` (true only for `CANDIDATE` or `DEFLATION_FAIL`). It is bookkeeping,
  never a pass, and never changes status or counts. `lineage_r2` (R² against up to 20 earlier factors; `composite_suspect` at 0.5 or more) is diagnostic only.
- **Futures funding.** `--funding-dir` reads existing Binance funding tables (no downloads) and adds `$funding_sum`, `$funding_last` and `$funding_count`.
  A settlement counts in the UTC day of its `known_from`. Missing stays NaN, never filled. A table with any 2024-or-later row is refused.
- **Thirds and ties.** The rule is `alpha_cli._rdagent_membership.third_weights`, not in the worker. A tie across a third's boundary shares membership among
  the tied names. The page also holds the do-not-change list and the tie diagnostics.

## Propose and discuss

The full text is in [propose-and-discuss.md](propose-and-discuss.md).

- `--discuss` on the launch pauses each round after the family and declaration checks and before any coding; `alpha ledger proposal` shows the ideas.
- Reply with `alpha ledger reply`: `--drop`, `--revise`, up to two `--idea`, one `--note`. Ideas you leave out are built as proposed.
- A note is one-way: it guides the next proposal. The agent does not answer questions.
- A stand-in user (`--as stand-in`) only discusses ideas. Only the owner approves reserved-data use, promotion, paper or live trading and guard changes.
- The agent's reflection is always passed on in full, also after a drop.

## Where things live

- Worker scripts (this folder): `factor_loop_launch.py` (launch), `factor_loop_entry.py` (runs the loop), `alpha_factor_judge.py` (the classes RD-Agent
  calls), `alpha_factor_data.py` (panel and funding files), `discussion.py` (the proposal pause), `model_gateway.py`, `research_memory.py`,
  `idea_families.py`, `loop_guard.py`, `universes/*.json`, and the `*-requirements.lock` files.
- ALPHA code the loop calls (`apps/alpha-cli/src/alpha_cli/`): `rdagent_factor_eval.py`, `_rdagent_judge.py`, `_rdagent_membership.py` (thirds and ties),
  `_rdagent_identity.py`, `rdagent_discussion.py`, `ledger_cmds.py`.
- Tests: `tests/unit/test_rdagent_*.py`; the thirds and ties tests are `test_rdagent_ties_and_thirds.py`.
- Rules and budgets: [worker invariants](../../docs/reference/invariants/rdagent.md). Why the part exists:
  [RD-Agent component](../../docs/reference/project/components/rd-agent.md).
- Older material (the pinned fixture, rule and stock probes, the model gateway, research memory, failure reasons, identity breaks and every
  fix-up): [CHANGE-NOTES.md](CHANGE-NOTES.md).

## Moved from the project page

The dated decisions, the plan and the links that the RD-Agent project page used to carry are in
[rd-agent-detail.md](../../docs/reference/project/rd-agent-detail.md) (decisions on the Codex route, DeepSeek through OpenRouter, the first real
runs, the discussion plan, backlog and decision records).
