# RD-Agent worker: the current page

This page says what the RD-Agent worker does today, how to launch it, how to propose and discuss ideas, and what must not change. The dated
change notes, the pinned probe and the older fixtures are in [CHANGE-NOTES.md](CHANGE-NOTES.md); nothing was deleted, only moved there.
The routing page is [CONTEXT.md](CONTEXT.md).

On this page: [What the loop does today](#what-the-loop-does-today), [How to launch](#how-to-launch),
[Propose and discuss](#propose-and-discuss), [Shortlist bookkeeping](#shortlist-bookkeeping), [Futures funding](#futures-funding),
[Thirds and ties](#thirds-and-ties) (with its do-not-change list), [Where things live](#where-things-live).

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

## How to launch

```sh
bash scripts/setup_rdagent.sh --with-factor-runtime      # once; hash-pinned Python 3.11 runtime
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

### Shortlist bookkeeping

Every new evaluation factor and its trial-ledger row records `shortlist`: true only for
`CANDIDATE` or `DEFLATION_FAIL`, after the declared primary screen, spread and replay passed.
Shortlisted is not a pass, not a candidate, and not evidence of profit. This flag never changes
status, confirmed counts, screen cutoffs, deflation N or family counts. Old missing flags mean
"not recorded", never false. It is bookkeeping for a later owner-approved confirmation stage;
this addition reads no reserved data and grants no confirmation authority.

For shortlisted factors, `lineage_r2` uses the twin check's hash-bound factor-value Parquet files
on the same panel. `pooled-xs-rank-ols-v1` ranks finite values within each date, uses average tied
ranks scaled to [-0.5, 0.5] (a singleton has rank zero), then selects at most 20 earlier judged
factors by absolute pooled rank correlation, with ties in ledger order. Repeats, imports and
failed, unstable or look-ahead code store no values and supply no regressor. All finite target rows enter one pooled OLS fit
without an intercept; missing regressor cells contribute zero. The adjusted R² is
`max(0, 1 - (SSE / (n - rank(X))) / (sum(y²) / n))`; `lineage_regressors` records the column count.
`composite_suspect` is true at R² ≥ 0.5: "looks like a blend of earlier tries", diagnostic only.
Fewer than 1,000 target rows, no earlier factor, a constant target, or unavailable earlier value
archives give null with `lineage_reason`; no proxy or incomplete top-20 selection is invented.
If the calculation itself fails, the row records null and the error as `lineage_reason`; the verdict stands.
Retain each earlier factor's dated instrument values and their hash to make that comparison possible.
`test_rdagent_shortlist.py` checks blends, independent noise, missing values and unchanged decisions.

### Futures funding

`factor_loop_launch.py run --funding-dir <data_dir>` (also the evaluator's `freeze` option)
reads existing `context/binance/um/funding/<SYMBOL>.parquet` tables; no downloads.
`alpha_data.context.daily_funding_with_sources` verifies each sidecar SHA-256 and returns daily
sums, last rates and settlement counts plus source hashes. The settlement's `known_from` instant
chooses its UTC day: `[d 00:00, (d+1) 00:00)`. A settlement at the next midnight plus 8 ms belongs
to the next day. Actual rates are summed regardless of 8h/4h/2h or unknown intervals. Empty days
have no row. A table containing any 2024-or-later row is refused even outside the requested range.

Freeze keeps `PANEL_COLUMNS` and `panel.parquet` unchanged. `_panel_funding` joins the raw ticker
and date before identity relabelling; successors bring their own perp's rates. Reused tickers
lose funding on and after their declared break. `FUNDING_EXCLUSIONS` omits COCOSUSDT because
"perp identity across the 2023 rename is unresolved"; 1000-prefixed perps are not mapped.
Only panel keys survive. `panel/funding.parquet` and the receipt's optional `funding` block bind
the side table hash, source hashes, funded names and annual panel instrument-day coverage.
The launcher records the supplied directory in its arguments and receipt.

`alpha_factor_data.prepare` adds float64 `$funding_sum`, `$funding_last`, `$funding_count` to full,
debug and every cut, and records `funding_sha256`. Missing stays NaN: no perpetual or no settlement
that day (roughly four in ten coin-days, and most later-delisted coins never had a perpetual).
Never fill with zero or carry forward. The generated README explains the columns and midnight
boundary; the scenario mentions them only when they exist in the prepared data. Without the
option, freeze and prepare retain their original outputs, including receipts (HDF5 files embed
write times, so their bytes differ between any two runs, even of unchanged code; frames are equal).

The open `futures funding` family recognises funding, carry, basis and perp and is matched first,
so `funding_momentum_7d` is a funding idea, not a closed price family; no existing counts change. Eligibility uses the archived, hash-checked source: literal `$funding_` selectors in
Python subscripts or `.get`, `.filter`, `.__getitem__` calls intersect the normal mask with that
day's funding rows. Comments and standalone strings do not count. This is syntax, not data-flow
analysis: dynamic column names can be missed, and an unused selector or a selector on a different
object can count. Output values never choose the mask. Funding-enabled successful factors require
archived source. Trial rows (also in evaluation records) include `eligibility: "perp-funding"`,
`mean_eligible_names` over exploration days and funding hash. `input_columns` lists only literal
`$` selectors read by the source, including price columns, with `input_columns_method: source-selectors`.
If source is missing, the factor failed, or no literal selector is detected, no columns are listed
(as before) and `input_columns_method` says `fallback` and why. This does not change eligibility.

The unchanged coverage threshold is 80%; half of funded names is still DEGENERATE. At least five
finite names are needed on a decision day (the existing gap policy skips thin days).

Synthetic checks: `test_context_daily_funding.py` (poison, prefixes, intervals, absent days,
reserved rows, checksum); `test_rdagent_funding_columns.py` (identity join, partitions, source
selectors, coverage, price-only parity, pre-change freeze bytes and prepare frames).

### Thirds and ties

The rule lives in `alpha_cli._rdagent_membership.third_weights`
(`apps/alpha-cli/src/alpha_cli/_rdagent_membership.py`), not in the worker: `alpha_factor_judge.py` runs inside
RD-Agent's environment, imports no ALPHA package and calls the evaluator `alpha_cli.rdagent_factor_eval` as a
subprocess. Tests: `tests/unit/test_rdagent_ties_and_thirds.py`.

Thirds use `k = max(1, round(n/3))` among finite ranks. A tie group crossing a third's boundary receives
`s/g` membership per name (s remaining slots, g tied names); portfolio weights are `(s/g)/k`.
The spread, both replay paths and bucket reports share `_rdagent_membership.third_weights`.
Spread returns use these membership units divided by k; replacement turnover sums positive changes
in membership units divided by the new k, and estimated costs use that turnover. Replay targets
use the same weights for actual fills, fees, slippage and turnover. Without ties, membership is
exactly 0 or 1 and the old arithmetic is preserved. The legacy alternate-tie spread field equals
`mean_spread`; displayed figures and the sign check use this same spread.
`tie_share` is the daily mean fraction of finite names sharing a value. `boundary_tie_share` counts
names in a tie crossing either third boundary, once per name; empty days contribute zero.
`all_tied_day_share` retains the old fully tied-day fraction and its unchanged 5% screen guard. About
85 funded names can be screened and give 28 names per third if all have values; breadth alone
never grants a pass. Outcomes remain panel spot returns; clocks, cost rates, pass thresholds, deflation,
counting and twin rules are unchanged. Price-only evaluations retain the original eligibility.

Do not change without the owner:

- clocks, cost rates, pass thresholds, deflation, trial counting and twin rules (all unchanged by the thirds rule);
- the 80% coverage threshold, the five-name minimum (`MIN_NAMES`) and the 5% all-tied-day guard;
- a nonpositive spread stays `SPREAD_FAIL`: a stricter gate, never a pass;
- the loop never sees data on or after 2024-01-01 ([reserved period](../../docs/reference/project/reserved-period.md));
- keep the tie diagnostics `tie_share`, `boundary_tie_share` and `all_tied_day_share`, and the legacy field `alternate_tie_order_mean_spread`, which equals `mean_spread`;
- the instrument order never chooses a member of a tie, and the worker keeps importing no ALPHA package;
- never weaken a bias guard or oracle to get green; run `uv run python scripts/gate.py check`.

## Propose and discuss

Add `--discuss` to the factor-loop launch to see each round's ideas after the family and
declaration checks and before any coding. In another terminal, use the folder you passed to
`--run-dir`:

```sh
alpha ledger proposal --run-dir "$run_dir"
alpha ledger reply --run-dir "$run_dir" --as owner --drop "1=reason" --revise "2=note"
alpha ledger proposal --run-dir "$run_dir" --last-decision
```

Use a name or the list number. Ideas you leave out are built as proposed. Add up to two ideas of your own with `--idea` and
a note for this run with `--note`. A stand-in answers with `--as stand-in`, recorded as
`stand-in user, not the owner`. The run keeps the proposal, the reply and the decision under
`discussion/round-<n>/`; each built idea records who proposed it in `origin` and who answered in
`answered_by`. The deprecated `author` on built ideas holds the same value as `answered_by`.

A stand-in user only discusses ideas. Only the owner approves: reserved-data slots, promotion, paper or live trading, and guard changes
([rule](../../docs/reference/project/owner-decisions-5.md#2026-11-18-stand-in-user-while-ideas-are-throwaway-tests)). Owner approvals go only through
`apps/alpha-cli/src/alpha_cli/owner_auth.py`, and the `pre-owner-action-guard` hook in `scripts/claude_hooks.py` blocks agent tools
from the owner-action routes.

- The proposal starts with the deadline and timeout action, then a trader-style summary per idea and a caution about
  on/off rules. It names refusals before the pause and the chat calls spent asking again. Chat and embedding calls each
  have their own usage line or count and cap. Use `--details` for the meaning of each closed idea type.
- The proposal and `--last-decision` give one result per selected idea when the evaluation is ready. Between proposals
  the command reads `discussion/status.json`. Earlier rounds estimate time from receiving a reply to the next pause.
  The final round estimates time to results using this run’s median build time. Without a measurement it says “several minutes”.
- Every proposer, including the experiment writer and both steps of a re-ask, sees this run’s drop reasons, revision notes
  and notes to the agent. The fixed data warning precedes one JSON line, newest first, with a 4,000-character cap and a
  count of older choices left out. Feedback sees only the names you dropped, in the same kind of block, with a fixed
  sentence: you chose not to build them, a drop is not a failure, and it assesses only the ideas that were built.
  ALPHA's verdict stays the decision. A name you dropped is shown as "Not offered again" if proposed again: not a failed
  try, no trial row. Only your reply can drop. To build it after all, add it as your own with `--idea`.
- A dropped idea is never built: no trial row, no family failure, no look. Dropping is only
  possible before coding. A second reply, or one after the round closed, is refused and kept as
  `refused-reply-<k>.json`.
- One extra proposal call covers all revisions and added ideas. The gateway counts it toward the
  usual caps. At the cap, or if the answer is unusable, those ideas are dropped with the reason
  and the accepted ones are built. The decision lists what the revision did and did not do (`honoured`, `not_honoured`:
  up to five statements of 200 characters); a missing or malformed list is left out and shown as not said. A revision that
  returns a dropped name, or a dropped family neither the note nor the revised idea had, is dropped with "revision returned
  a dropped idea", at no extra call. The revision sees closed idea types and their meanings before it writes. When a
  request needs a closed type, it should explain that and give the nearest open alternative. A refused revision names
  the type, its failed tries and the limit. Replacements meet the same checks as any idea.
- For your own idea the agent must use only the inputs and terms you gave. It records its simplest readings of open
  choices in `agent_choices`, with the same limits as revision statements. The decision prints those choices under the idea.
- Notes, reasons and ideas are at most 500 characters each and reach the agent as quoted data.
  They cannot change a test, threshold or limit. A reply only chooses what is built; it never
  approves, admits or promotes anything.
- The default wait is 30 minutes, then the ideas are built as proposed. `--discuss-wait-minutes N`
  changes the wait; `--discuss-on-timeout stop` stops cleanly before coding instead. The launch's
  `--wall-seconds` limit still applies, so set it longer than the waits you expect.

Every proposed sentence carries `plain_summary_status` (`ok`, `missing` or `rejected`).
With the pause off, only the additive summary fields enter the round and trial records.

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
