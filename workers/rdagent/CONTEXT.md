---
owner: rd-agent worker
sources:
  - workers/rdagent/*.py
  - workers/rdagent/pyproject.toml
  - workers/rdagent/uv.lock
verified: 095bf593cbaa33bc
---

# RD-Agent worker workspace

## Purpose

Flat entry scripts and pinned locks that run Microsoft RD-Agent's native loops (synthetic
fixtures, rule and costed probes, the stock RDLoop) in their own environments for the CLI's
native job supervisor, plus `model_gateway.py`, the local program through which RD-Agent reaches
a model, and the ALPHA-judged factor loop (`factor_loop_launch.py`, `factor_loop_entry.py`,
`alpha_factor_judge.py`, `alpha_factor_coder.py`, `alpha_factor_data.py`; ADR-0049) with its
cross-run research memory (`research_memory.py`) and its universe files (`universes/*.json`, ADR-0055), and RD-Agent's own run viewer
(`rdagent_viewer.py`, `rdagent_ui_entry.py`, `ui-requirements.lock`; local only). The judge leaves
human-authored rule trials (`AlphaRuleTrialV1`, written by `alpha_cli.rdagent_rule_family`) out of
RD-Agent's proposal summary. It is a separate uv project (`package = false`) with its own lock; no
ALPHA package imports it, though its probes import ALPHA packages inside qualified profile environments. It has
no market, inference or evidence authority.

## Read first

| Read | Section | When |
|---|---|---|
| [worker invariants](../../docs/reference/invariants/workers.md) | Shared rules | always |
| [worker invariants](../../docs/reference/invariants/workers.md) | RD-Agent worker | always |
| [command line native](../../docs/reference/invariants/cli-native.md) | — | always |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Owner authority | changing what a native result may claim |
| [what this part is for](../../docs/reference/project/components/rd-agent.md) | — | why it exists; before you keep, shelve or remove it |

## How to change it

- Code: the scripts in `workers/rdagent/` and the lock files beside them (`model_gateway.py` is standard library only and
  imports neither ALPHA nor RD-Agent; `install_stock_profile.py` and `stock-requirements.lock` build the Python 3.11
  stock runtime; `--profile ui` records the viewer runtime).
- Gateway embedding backends and accounting live in `gateway_embeddings.py`: local by default,
  or an explicitly priced provider model. Both share the 2,000-attempt guard; paid embeddings
  spend money but no chat calls. Paid memory inputs batch by 32, with per-request receipts.
  Model-bound memory uses a sidecar; `embedding_eval.py` checks retrieval.
  See the worker invariants for accounting and compatibility.
- Exact-text embedding reuse is process-local; `idea_families.py` parses named inputs and
  `loop_guard.py` closes exhausted-provider rounds, including proposal, without inventing trials.
  Descriptions declare sign, primary clock and economic reason; past-return sign variants share closure.
  The code-critic guard preserves execution/value feedback and skips later critics in the failed round.
  Internal coding errors preserve completed factors for judging; two consecutive failures stop the run.
  Restored prompts retain four full same-panel rounds; the other rounds stay as summaries.
  Memory search tables use one vector dimension; restored panel provenance includes run receipts.
- Optional futures funding is a separate hash-bound panel table; daily timing, identity joins and
  factor-specific eligibility: [README](README.md#futures-funding). Tests: `test_rdagent_funding_columns.py`.
- Chat cache/provider observations and receipt summaries live in `gateway_usage.py`; API sessions
  use the run id unless `--no-router-session` is set. Contracts: `test_rdagent_gateway_usage.py`.
- Tests live in the root suite: `tests/unit/test_native_*.py`, `test_rdagent_model_gateway.py`, `test_rdagent_provider_embeddings.py`,
  `test_rdagent_embedding_{cap,eval}.py`, `test_setup_rdagent.py`, `test_rdagent_viewer.py`, `test_rdagent_factor_{eval,judge,launch}.py`,
  `test_rdagent_research_memory.py`, `test_rdagent_{gapped_universe,identity_breaks}.py` (the factor-runtime cases need
  `ALPHA_FACTOR_PYTHON` as well). Tests that need the RD-Agent source skip unless `ALPHA_RDAGENT_SOURCE` (and, for stock lanes, `ALPHA_STOCK_PYTHON`) is set.
- There is no CI gate component for this worker; run `uv run python scripts/gate.py check` from
  the repository root.
- Editing `alpha_core`, `alpha_patterns` or `alpha_strategies` source changes the installed rule
  profiles' measured environment; rebuild them (see the native file).

- The Workstation's RD-Agent panel reads existing records only; it cannot start the worker.
  Its projection, status wording and record limitations belong to the
  [web workspace](../../apps/alpha-web/CONTEXT.md), not to the loop or its trial-count rules.
- The evaluator appends shortlist and lineage diagnostics; the worker preserves that record.
  Policy and regression convention: [README](README.md#shortlist-bookkeeping); no judging rule changes.
- Fractional thirds, tie diagnostics and source input columns: [README](README.md#futures-funding).
  Feedback separates global looks from family failures; session drift suggestions follow the frozen source.
  Tests under `tests/unit/` cover these in `test_rdagent_ties_and_thirds.py`, `test_rdagent_funding_columns.py` and `test_rdagent_families.py`.

## Outputs

- Root tests under `tests/unit/test_native_*.py` and `tests/unit/test_rdagent_model_gateway.py`.
- The owning document: `docs/reference/invariants/workers.md` § RD-Agent worker. Identity split counts
  and write-offs reach proposer feedback; rescaling, reproducibility and family refusal rules: [README](README.md#identity-breaks-across-a-gap).
