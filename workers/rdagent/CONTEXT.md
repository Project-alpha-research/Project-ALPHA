---
owner: rd-agent worker
sources:
  - workers/rdagent/*.py
  - workers/rdagent/pyproject.toml
  - workers/rdagent/uv.lock
verified: 095f2f22bb96915a
---

# RD-Agent worker workspace

## Purpose

Flat entry scripts and pinned locks that run Microsoft RD-Agent's native loops (synthetic fixtures, rule and costed probes, the stock RDLoop) in their own
environments for the CLI's native job supervisor, plus `model_gateway.py`, the local program through which RD-Agent reaches a model, and the ALPHA-judged
factor loop (`factor_loop_launch.py`, `factor_loop_entry.py`, `alpha_factor_judge.py`, `alpha_factor_coder.py`, `alpha_factor_data.py`; ADR-0049) with its
cross-run research memory (`research_memory.py`) and its universe files (`universes/*.json`, ADR-0055), and RD-Agent's own run viewer (`rdagent_viewer.py`,
`rdagent_ui_entry.py`, `ui-requirements.lock`; local only). The judge leaves human-authored rule trials (`AlphaRuleTrialV1`, written by
`alpha_cli.rdagent_rule_family`) out of RD-Agent's proposal summary. It is a separate uv project (`package = false`) with its own lock; no ALPHA package
imports it, though its probes import ALPHA packages inside qualified profile environments. It has no market, inference or evidence authority.

## Read first

| Read | Section | When |
|---|---|---|
| [worker invariants](../../docs/reference/invariants/workers.md) | Shared rules | always |
| [RD-Agent invariants](../../docs/reference/invariants/rdagent.md) | Boundary and authority | always |
| [command line native](../../docs/reference/invariants/cli-native.md) | Synthetic only | native fixtures and rule jobs: what a native result may claim |
| [command line native](../../docs/reference/invariants/cli-native.md) | Launch identity | launching a native job or changing its identity |
| [command line native](../../docs/reference/invariants/cli-native.md) | Approval fingerprints | approving a native job or changing its fingerprint |
| [command line native](../../docs/reference/invariants/cli-native.md) | Process ownership | starting, stopping or cleaning up native processes |
| [command line native](../../docs/reference/invariants/cli-native.md) | Results and inspection | reading or showing a native result |
| [research integrity](../../docs/reference/invariants/research-integrity.md) | Owner authority | changing what a native result may claim |
| [RD-Agent invariants](../../docs/reference/invariants/rdagent.md) | Install and runtimes | building a runtime profile, the source pin or its measure |
| [RD-Agent invariants](../../docs/reference/invariants/rdagent.md) | Model gateway | changing the model route, budgets, receipts or embeddings |
| [RD-Agent invariants](../../docs/reference/invariants/rdagent.md) | Factor loop and judging | changing the factor loop, judge, coder or evaluator |
| [RD-Agent invariants](../../docs/reference/invariants/rdagent.md) | Research memory | changing families, discussion, memory, verdicts or rule families |
| [RD-Agent invariants](../../docs/reference/invariants/rdagent.md) | Panels and identity | changing panel building, renames, splits or identity joins |
| [RD-Agent invariants](../../docs/reference/invariants/rdagent.md) | Viewer | changing the run viewer |
| [what this part is for](../../docs/reference/project/components/rd-agent.md) | — | why it exists; before you keep, shelve or remove it |
| [worker README](README.md) | — | launching a loop, propose and discuss (stand-in answers), thirds and ties with their do-not-change list, futures funding |
| [change notes](CHANGE-NOTES.md) | — | the history of a rule, the pinned probe, the model gateway, research memory; every dated fix-up |

## How to change it

- Code: the scripts in `workers/rdagent/` and the lock files beside them (`model_gateway.py` is standard library only and imports neither ALPHA nor RD-Agent;
  `install_stock_profile.py` and `stock-requirements.lock` build the Python 3.11 stock runtime; `--profile ui` records the viewer runtime).
- Gateway embedding backends and accounting live in `gateway_embeddings.py`: local by default, or an explicitly priced provider model. Both share the
  2,000-attempt guard; paid embeddings spend money but no chat calls. Paid memory inputs batch by 32, with per-request receipts. Model-bound memory uses a
  sidecar; `embedding_eval.py` checks retrieval. See the worker invariants for accounting and compatibility.
- The [proposal pause and stand-in answers](README.md#propose-and-discuss) (`--discuss`; a stand-in answers with `alpha ledger reply --as stand-in`;
  the owner rule is the [stand-in entry](../../docs/reference/project/owner-decisions-5.md#2026-11-18-stand-in-user-while-ideas-are-throwaway-tests))
  exchange JSON with the CLI in `discussion.py` after the family guard. Each proposer and re-ask reads choices from this run's decisions.
  Feedback reads only dropped names. The worker records revision explanations, re-ask costs and build times. Tests: `test_rdagent_discussion{,_commands}.py`.
- Exact-text embedding reuse is process-local; `idea_families.py` parses named inputs and `loop_guard.py` closes exhausted-provider rounds, including
  proposal, without inventing trials. Descriptions declare sign, primary clock and economic reason; past-return sign variants share closure. The code-critic
  guard preserves execution/value feedback and skips later critics in the failed round. Internal coding errors preserve completed factors for judging; two
  consecutive failures stop the run. Proposal history fits a character budget. New factor rows record the family and per-factor critic outcome. Vector rebuild
  receipts identify omitted nodes and causes. Restored panel provenance includes run receipts.
- Optional futures funding is a separate hash-bound panel table; daily timing, identity joins and factor-specific eligibility:
  [README](README.md#futures-funding). Tests: `test_rdagent_funding_columns.py`.
- The scenario checks the prepare receipt or HDF columns once. Proposal context, family closure and feedback share one parsed ledger per round, refreshed when
  size or modification time changes. Tests: `test_rdagent_read_once.py`.
- Chat cache/provider observations and receipt summaries live in `gateway_usage.py`; API sessions use the run id unless `--no-router-session` is set.
  Contracts: `test_rdagent_gateway_usage.py`.
- Tests live in the root suite: `tests/unit/test_native_*.py`, `test_rdagent_model_gateway.py`, `test_rdagent_provider_embeddings.py`,
  `test_rdagent_embedding_{cap,eval}.py`, `test_setup_rdagent.py`, `test_rdagent_viewer.py`, `test_rdagent_factor_{eval,judge,launch}.py`,
  `test_rdagent_research_memory.py`, `test_rdagent_{gapped_universe,identity_breaks}.py` (the factor-runtime cases need `ALPHA_FACTOR_PYTHON` as well). Tests
  that need the RD-Agent source skip unless `ALPHA_RDAGENT_SOURCE` (and, for stock lanes, `ALPHA_STOCK_PYTHON`) is set.
- Run `uv run python scripts/gate.py check` at the root. The worker has no CI gate component.
- Editing `alpha_core`, `alpha_patterns` or `alpha_strategies` source changes the installed rule profiles' measured environment; rebuild them (see the native
  file).
- The Workstation's RD-Agent panel reads existing records only; it cannot start the worker. The [web workspace](../../apps/alpha-web/CONTEXT.md) owns its
  projection, status wording and record limitations.
- The evaluator appends shortlist and lineage diagnostics; the worker preserves that record. Policy and regression convention:
  [README](README.md#shortlist-bookkeeping); no judging rule changes.
- Thirds and ties: the rule is `third_weights` in `apps/alpha-cli/src/alpha_cli/_rdagent_membership.py`, tested by
  `tests/unit/test_rdagent_ties_and_thirds.py`. This worker cannot import it: `alpha_factor_judge.py` runs in RD-Agent's own environment with no ALPHA package
  and calls the evaluator as a subprocess. Rule and do-not-change list: [README](README.md#thirds-and-ties).
- Source input columns: [README](README.md#futures-funding). Feedback separates global looks from family failures; session drift suggestions follow the frozen
  source. Tests: `test_rdagent_funding_columns.py`, `test_rdagent_families.py`.

## Outputs

- Root tests under `tests/unit/test_native_*.py` and `tests/unit/test_rdagent_model_gateway.py`.
- The owning document: `docs/reference/invariants/rdagent.md`. Identity split counts
  and write-offs reach proposer feedback; rescaling, reproducibility and family refusal rules: [change notes](CHANGE-NOTES.md#identity-breaks-across-a-gap).
