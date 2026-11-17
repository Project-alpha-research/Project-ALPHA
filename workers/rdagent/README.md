# Pinned native loop development probe

This isolated Python 3.12 project exercises RD-Agent commit
`484776c211e4fbbeef03e0ec00d6bbee7362a4f4` with fixed synthetic inputs. It has no application
dispatch route. No ALPHA package imports this worker. `NativeFixtureLoop` explicitly uses
upstream `LoopMeta` and inherits upstream `run`, `_run_step`, `dump` and `load` without overrides.
That original fixture never imports or instantiates stock `RDLoop`; the separate
stock continuation diagnostic below does.

## Reproduce

Obtain upstream commit `484776c211e4fbbeef03e0ec00d6bbee7362a4f4` as a pristine checkout, either
from `https://github.com/microsoft/RD-Agent/archive/484776c211e4fbbeef03e0ec00d6bbee7362a4f4.tar.gz`
(expected archive SHA-256 `4c5d1c792b133d7148bb4d59aea09b8accf4d14deb4a10ffed276ce178dd855c`) or by
fetching that exact commit with git and checking `git rev-parse HEAD`. Keep it unmodified.
Its root contains a top-level `test/` package, which the shadow check below always rejects because
`test` is a standard-library name. Point `ALPHA_RDAGENT_SOURCE` at a separate derived root holding a
byte-identical copy of `rdagent/` plus upstream `LICENSE` (and optionally `pyproject.toml`); nothing
outside `rdagent/` is imported. Record the pristine origin, HEAD and every excluded entry.

The probe verifies all 694 files under `rdagent/` (except bytecode) against the aggregate digest
in `source_pin.py` before any upstream import, rejects symlinks/drift and records each imported
source file's hash. That tree digest is the only measured source identity: results report
`source_pin.verified.source_tree_sha256`, while the commit and archive checksum appear only under
`source_pin.expected` and are listed in `source_pin.not_verified`. Verify the archive checksum
yourself when you download it. Source remains external; no upstream scheduler is vendored here.
The external source root is never placed on `sys.path`: a narrow finder resolves only `rdagent`
within the verified directory and binds each worker helper to its reviewed source file. Importable
source-root shadows of worker, standard-library or installed dependency modules are rejected.
The fresh bytecode cache is selected before importing even the local source verifier. Every
successful probe validates both upstream and worker helper origin hashes.

From the repository root, using the normal ALPHA test environment:

```sh
uv sync --locked --project workers/rdagent
ALPHA_RDAGENT_SOURCE=/absolute/path/to/derived-rdagent-484776-root \
  uv run --no-sync pytest -q tests/unit/test_native_loop_conformance.py
```

Optionally set `ALPHA_RDAGENT_RECEIPTS` to a disposable evidence directory. Each probe writes a
unique JSON receipt there, preserving failures across reruns. Without an explicit source path,
the public tests skip and confer no native qualification. The isolated `uv.lock` is a focused
import dependency subset, **not** upstream's full application dependency environment. Root
dependencies and lock are unchanged.

## Install on a development machine

`bash scripts/setup_rdagent.sh` (idempotent; about 1.1 GB, under a minute with a warm uv cache)
fetches the pinned commit into `.alpha/state/runtime/rdagent-pristine` when absent, derives
`.alpha/state/runtime/rdagent-source`, verifies the source-tree digest, syncs `.venv` and builds
and validates `.venv-rule-qualified` and `.venv-economics-qualified`. It is the RD-Agent part of
`ALPHA_CLOUD_FOUNDATION=1 ALPHA_CLOUD_RDAGENT=1 scripts/cloud_setup.sh` without Git hooks, npm,
browser download or fontconfig. All of it is gitignored (`.alpha/state/`, `.venv-*/`). It prints
`export ALPHA_RDAGENT_SOURCE=…`, which runs the conformance, W04 and rule tests. Two optional
flags add the rest (both idempotent, both off by default so the default install stays small):

- `--with-daily-container` pulls exactly one image, `python@sha256:aa943ce4…d159`
  (`python:3.12-slim`, about 120 MB), checks that it is image
  `sha256:ae4e8b7c575fabea88a029b6cae757f342ca2525e07f7c22272d5105c346b35e`, and runs
  `qualify_daily_container.py` (an offline import smoke under the daily security policy; no
  derived image is built), which writes `.alpha/state/runtime/daily-container.json`. Without it the
  13 daily-study tests that need the image are skipped with that reason.
- `--with-stock-runtime` builds the stock `RDLoop` runtime bundle
  `.alpha/state/runtime/rdagent-stock-py311/` (`venv/`, `dependencies.lock.txt`,
  `stock-profile.json`; about 230 MB) on CPython 3.11 from
  [`stock-requirements.lock`](stock-requirements.lock) with `--require-hashes --no-deps`, then
  `install_stock_profile.py` proves the installed distributions are exactly the 60 locked ones and
  records an inventory digest (`--verify` rechecks it on every run). It prints
  `export ALPHA_STOCK_PYTHON=…/venv/bin/python` and a fresh `ALPHA_STOCK_RECEIPTS` directory.

**Why Python 3.11 for the stock runtime:** upstream RD-Agent at the pin declares and tests only
3.10 and 3.11 (`pyproject.toml` classifiers; `constraints/3.10.txt`, `constraints/3.11.txt`), and
the earlier hand-built stock runtime was 3.11. The stock bundle imports no ALPHA package, so the
project's 3.12 requirement does not apply to it. The lock is the minimum closure for this fixture
path (`stock_fixture_entry.py` → `rdagent.core.conf`, `rdagent.components.workflow.rd_loop` and the
core records): `docker`, `rich`, `numpy`, `openai`, `tiktoken`, `litellm` plus the conformance
imports and their declared dependencies; pandas and scikit-learn are not imported and not
installed. It was resolved against upstream `constraints/3.11.txt` (so `dill==0.3.9` and
`psutil==6.1.0`, not the conformance environment's newer pins) with package dates up to the pin's
commit date. `litellm` is pinned to 1.97.0, the version upstream's own `constraints/3.10.txt`
names; it is also the library a future model connection would go through, which this runtime does
not make (the fixture clears all model settings and blocks the network).

Smoke check: `uv run python scripts/run_owned_test.py -- uv run pytest -m smoke
tests/smoke/test_rdagent_smoke.py`.

## Contracts exercised

- `direct_exp_gen` returns native `Hypothesis` and `Experiment` under `propose`/`exp_gen`.
  Coding is a noop, running attaches only fixed metrics, feedback is a native
  `HypothesisFeedback` subclass, and record uses native `Trace.sync_dag_parent_and_hist`.
- SUPPORTED, CONTRADICTED, INCONCLUSIVE and INVALID are **supplied synthetic labels**, not
  classifications produced by ALPHA's scientific acceptance logic. Labels and metric names,
  values and units survive recording and signed checkpoint loading. Native `decision` and
  `acceptable` remain false for every fixture; truth conversion raises instead of collapsing
  a label into generic success. No label grants evidence or approval authority.
- Native `run(step_n=0)` executes one stage; `step_n=1` executes two. These post-effect stop
  knobs are not admission budgets. A separate ephemeral fixture allowance checks each stage
  before its fixed operator, and remains outside the pickle. It tests only the fixture guard,
  **not ControlStore reservation, settlement, exposure or economics integration**.
- One live fixture owner guards the entire run/load/resume operation. Native tasks are drained
  before unlocking. Duplicate start, stale/foreign checkpoint and concurrent continuation are
  rejected. Successful checkpoints resume once under that same owner. Cancellation closes the
  owner and retains the fixture charge for interrupted work.
- Upstream advances its in-memory cursor in `finally` even when a stage is cancelled, but writes
  no checkpoint for that incomplete stage. Tests load the actual last successful checkpoint
  and reject further execution through the cancelled owner. No durable consumption ledger or
  cross-owner recovery is added.

## Scope and limits

Every test launches a new sanitized subprocess in an empty temporary directory. Environment,
HOME, log path, signing-key path and bytecode cache are fixture-local. The key is generated by
the existing upstream signed-pickle implementation. An import allowlist excludes backends and
stock loops; Python audit tripwires reject network connection/DNS and subprocess effects. These
checks contain trusted fixture mistakes; they are not hostile-code or same-UID security isolation.

No real provider, LLM, generated code, market data, holdout, broker, live database, migration or
real owner-approval action executes. ALPHA retains admission/budget/exposure/execution/economics/
evidence/approval responsibility. Owner-death recovery, physical containment, production
activation and scientific artifact admission remain unqualified. Public focused checks are not a
full gate or release approval.

## Bounded W04 admission fixture

`test_native_w04_admission.py` composes this actual child with the existing synthetic process
owner and scratch-created ControlStore. It approves measured worker/code/lock/interpreter/config
fingerprints through existing synthetic test helpers, reserves the full remaining D1 envelope,
requires one reserved variant and positive CPU allocation, and commits a single trusted owner
claim before child effects.
The closed `native_loop` launcher accepts only fixed fixture modes; there is no caller command,
dynamic operator, provider, model or production route. Interpreter/config and lock identity are
measured; they do not qualify the installed dependency environment or enforce CPU/token usage.

The child receives a reference-only JSON admission identity, never a ControlStore handle or owner
lock. Its existing ephemeral stage guard derives `loop_steps` from the actual reservation. The
signed native pickle includes a digest of job/reservation/spec/manifest/owner/mode/allowance.
Resume is allowed only in the same live child; path, byte digest and admission binding are checked
before continuing. The reserve is charged once and never restored from checkpoint state.

The supervisor retains the actual native child handle and applies the existing independent lease
and process-group cleanup. After cleanup, exact feedback labels and metric names/values/units are
validated against the admitted fixed mode. Every successful result remains process-only and
`pending_scientific_admission` / `not_admitted`. No scientific run ID or completed D1 attempt is
invented. Failure/cancellation reconciles through existing failed-attempt/link/status records;
unknown cleanup or result/journal publication retains capacity and the complete charge.

The W04 process-only lifecycle event schema and fields are unchanged. The later closed rule
workflow adds the narrowly validated `rule_result` binding described below; old readers must not
write/read those new outcomes in a mixed deployment. Study `ExplorationMandateV1`
references grant no launch authority; this fixture is not a new registration in the closed
scientific operator registry. It exercises existing reservation exposure, not generic study/trial
admission or scientific acceptance. Full resource metering, durable scientific artifact admission,
cross-owner recovery and production activation remain W08 gaps. See
[`2026-10-26-native-w04-admission.md`](https://github.com/tradingsystem1880-eng/Project-ALPHA/blob/pre-thin-2026-11-14/docs/work/archive/2026-10/2026-10-26-native-w04-admission.md).

## Closed frozen-rule authority profiles (2026-10-26)

See the [current handoff plan](https://github.com/tradingsystem1880-eng/Project-ALPHA/blob/pre-thin-2026-11-14/docs/work/archive/2026-10/2026-10-26-native-rule-authority.md).
The old `.venv` and `uv.lock` above remain the W04 conformance environment. Two **fresh-only**
environments add closed position and costed synthetic profiles, with hash-pinned requirements
reusing already approved root/worker versions. Root `uv.lock` is unchanged. The economics profile
uses root-pinned Nautilus 1.228.0, pytz 2026.2 and tqdm 4.68.2; it does not overwrite the old profile.

On a fresh checkout with the normal locked root environment and complete pinned upstream available:

```sh
uv venv --python 3.12 workers/rdagent/.venv-rule-qualified
uv pip install --python workers/rdagent/.venv-rule-qualified/bin/python --require-hashes --no-deps -r workers/rdagent/rule-requirements.lock
.venv/bin/python -B workers/rdagent/install_rule_profile.py
uv venv --python 3.12 workers/rdagent/.venv-economics-qualified
uv pip install --python workers/rdagent/.venv-economics-qualified/bin/python --require-hashes --no-deps -r workers/rdagent/economics-requirements.lock
.venv/bin/python -B workers/rdagent/install_rule_profile.py --economics
```

`.gitignore` now covers both through its `.venv-*/` entry (checked 2026-11-14 with
`git check-ignore`); `cloud_setup.sh` still also lists `/workers/rdagent/.venv-rule-qualified/` and
`/workers/rdagent/.venv-economics-qualified/` in the clone-local `.git/info/exclude`. Unignored, the
generated environments would be hashed into the gate tree and scanned by ruff and semgrep as source.
These are generated-environment excludes, not test or coverage exclusions.

Do not run these commands over preserved environments. The installer copies complete noncache
source/resources, compares original distribution metadata to pyproject, preserves Requires-Dist,
and writes honest source-install provenance and RECORD. It invokes no build backend and installs
no editable hooks. It rejects symlinks, duplicate metadata and unexpected site hooks. Profile
inventories bind every installed dependency/source byte, source pyprojects and root/profile locks;
pre-effect admission and result checks compare them to the owner-approved fingerprints. Runtime
imports record actual package and metadata origins. Fresh bytecode is selected before imports.

The positions profile omits Nautilus, so alpha-strategies has an explicitly unsatisfied declared
dependency. Economics includes Nautilus and its required closure; alpha-data still has unqualified
provider dependencies, listed precisely in its installed PROFILE.json. Full package API qualification
is false for every local distribution. No fallback root sys.path or merged package environment is
used. These are local fixture source installations, not built wheels or upstream full applications.

V1 evaluates the original visible bars through actual rule_signal. V2 owns a separate seven-row
synthetic dataset (one warmup and six execution bars); it runs actual run_backtest/RuleStrategy
sequentially for the baseline and flat control before Feedback. The unchanged audit hook was
exercised by the real compiled engine. Only serializable canonical results enter checkpoints;
Nautilus resources are disposed by the canonical engine. Synchronous execution relies on the
external supervisor deadline; no immediate cooperative cancellation or hard real-time claim is made.

An exact approved contract and consumed real local-confirmation receipt are required before the
existing reservation/claim. Two outcome exposures share one trial. D0 uses the existing three-variant
engineering allowance; the caller must explicitly approve a sufficient budget. No repair/default
budget is invented. Signed checkpoint continuation and publication recovery do not create another
trial or refund charges. Scientific acceptance and empirical W08 remain blocked.

### Observed result byte binding

For closed rule success only, the trusted supervisor validates one bounded receipt read after
cleanup and records `rule_result` with nested schema `SyntheticNativeRuleObservationV1` and the
SHA256 of those same bytes. The existing100000-byte fixed receipt cap is enforced during that read.
This field is accepted only for the registered native rule reservation and clean successful
outcome; original process-only V1 fields stay unchanged. The issuer detaches and freezes the
closed nested string mapping; journal serialization copies it without exposing mutable owner
evidence. The hash alone proves no execution.
Completion compares the captured bytes to the trusted observation, publishes those exact bytes,
and pins `native_receipt_ref` in existing immutable attempt details. The verified completed-attempt
reader rechecks it before accepting derived numerical artifacts; general case summaries return
metadata and do not revalidate D1 artifacts. Self-consistent rehashing
of receipt/economics/projections cannot replace the recorded result. No SQL schema or ledger is
added. Unbound historical rule outcomes/artifacts cannot be upgraded into completion; retained
charge/capacity and investigation are required. Older writers/readers do not understand the new
rule binding; deployment cutover remains unqualified. Generic standalone UI/report readers keep
their existing integrity/unknown-state behavior and are not newly qualified by this boundary.

### Storage and history preflight

Linux execution may use the existing `cloud_root_identity` backend with control, manifests,
runs and bulk on one explicitly retained mount/device/owner. A study with a temporary duration
still needs retained storage: `/tmp`, tmpfs and overlay roots remain rejected, and the reserve
is the larger of 15% and 100 GB unless the owner has set an attributed value of at least 10 GB
for that root ([ADR-0043](../../docs/adr/0043-storage-reserve-is-owner-set.md),
[storage settings](../../docs/operations/storage-settings.md)). Verify underlying capacity and retention too; free space
reported by a thin virtual disk is not proof of available backing-disk space or a backup.

This option does not change the native `macos_volume_uuid` backend. Keep existing Mac profiles,
archives and authoritative history intact. A separate Linux root must not evade the existing
database-wide one-trial reservation guard. No new Mac/Linux UUID bridge is implemented.

Before designating an execution root, run the explicit-root metadata reader against existing
authority, using the installed project environment:

```sh
uv run python scripts/inspect_daily_rule_history.py --data-dir /absolute/existing/data
```

It opens one read-only schema-7 snapshot, selects closed routing metadata rather than project
prose or full contracts, and counts daily deep reservations across all projects. Counts cover
the entire selected store even when the contract list is paged. Event-study job counts also
cover unlinked jobs and other research routes; they do not prove process liveness. Malformed,
oversized, missing or older-schema history is unknown, never an empty installation. SQLite may
use WAL/SHM sidecars; this path does not write database records or change journal settings.

The report always grants no authority to initialize, migrate or switch roots. Reconcile prior
and unknown records first; do not import artificial ledgers, copy stale authority over later
state, or reset consumption. Actual activation still requires qualified Linux process/container
boundaries, retained storage, real input bindings and exact local owner confirmation. See the
[implementation record](https://github.com/tradingsystem1880-eng/Project-ALPHA/blob/pre-thin-2026-11-14/docs/work/archive/2026-10/2026-10-31-linux-storage-history.md).

## Stock RDLoop continuation diagnostic

The additive `stock_fixture_entry.py` now executes the actual pinned
`rdagent.components.workflow.rd_loop.RDLoop`. Its constructor loads fixed native
Scenario, HypothesisGen, Hypothesis2Experiment, Developer (coder/runner) and
Experiment2Feedback implementations from `stock_fixture.py`. All five stock stage
methods and upstream run/dump/load remain unchanged; the trace guard delegates
recording to native `Trace.sync_dag_parent_and_hist`. This uses an isolated pinned
source loader, not the stock CLI or a financial scenario.

The public `test_native_stock_fixture.py` obtains a reference through
`alpha_cli.native_stock_fixture.request_from_owner`, checking the existing exact
synthetic owner, canonical running reservation, cancellation, code/evaluator
fingerprint and minimum reserved envelope. It runs only with explicitly supplied
`ALPHA_RDAGENT_SOURCE`, `ALPHA_STOCK_PYTHON` and `ALPHA_STOCK_RECEIPTS` paths.
Root test dependencies and the full native application environment are separate;
no installation or dependency change is part of this slice.

The child rejects malformed/oversized requests before native imports, rechecks
worker/source identity, clears inherited environment, uses public synthetic
signing material and rejects network, provider, shell and credential-file effects.
Only the existing read-only `uname -p` and `ldconfig -p` dependency import probes
are allowed. No generated code or real tool executes.

Native `step_n=1` completes proposal AND coding before stopping. The last successful
signed checkpoint is hash-checked and loaded into a fresh checkout directory;
remaining running/feedback/record stages complete without repeating earlier
attempts. Pre-effect counters stay in the live fixture guard outside the pickle.
Tests also inject actual `asyncio.CancelledError` before the runner body, exhaust
fake model allowance before feedback and tamper checkpoint bytes before load.
The cancelled guard cannot continue, and the last successful checkpoint survives.
Cross-owner/process restart recovery remains unqualified.

`validate_stock_artifacts` reads bounded JSON and checkpoint bytes only, never
unpickles worker artifacts. It checks exact request/hash bindings, native class,
stage order, trace history/parent/loop identities, fixed synthetic observations
and unaccepted feedback. Canonical JSON comparison rejects boolean/numeric type
substitutions independently of hashes. Successful diagnostic output remains
`synthetic_only`, `not_admitted` and `production_dispatch=false`.

These references and counters are NOT durable consumption or a new ledger.
Repeated reference creation does not prevent another process from reusing one;
the whole existing reservation remains unchanged. CPU allocation is checked but
not enforced as a CPU cap; tests apply their own 40-second child timeout and reap
it. This does not qualify provider/subscription limits, dollar caps, installed
dependency integrity, hostile-code containment or production process ownership.
The standalone diagnostic adds no launch authority; the retained-owner successor
below extends only internal synthetic dispatch, using the existing accounting store.
Production registration, durable execution ownership, scientific admission,
protected-suite/full-gate qualification and independent release review remain gates.

## Retained-owner stock dispatch successor

`StockFixtureLaunch` is a second exact, closed launch identity accepted by the
existing internal synthetic owner. It inherits the non-scientific NativeLaunch
shape but rejects every study/authority and arbitrary mode. The runtime selector
names an existing bundle containing `venv/bin/python`, `venv/pyvenv.cfg` and
`dependencies.lock.txt`. Code/source/worker/interpreter/config/lock identity is
bound into the canonical approved invocation. This measures a runtime; it does
not install or qualify its dependencies, grant inference or bypass storage rules.
No public research command or production activation is added.

The existing `start_synthetic_owner` reconstructs that exact identity in its
retained owner process. `_Owner.spawn`, its `Popen`, immediate safety lease,
process-group cleanup and existing immutable observations remain the launch path.
The child receives only a fixed bounded reference, neither owner lock nor store.
The supervised workspace requires the existing synthetic marker and exact job
path. Its own environment is cleared before native settings import.

A stock claim carries its full launch-profile hash. Immediately before spawn,
`consume_before_spawn` uses the existing ControlStore write transaction to validate
the live owner/claim, active reservation, unchanged profile, stop/deadline state
and the fixed reserved envelope. One protected `native_invocation` event in
existing `job_events` records five stages/two fake-model/two fake-tool attempts;
commit precedes `Popen`. It is whole-invocation consumption, not measured API
usage or another ledger. No reservation/balance row is rewritten or refunded.

Rollback prevents spawn. A committed consumption followed by cancellation,
process-creation failure or lost availability cannot be reminted. Existing durable
claims prohibit relaunch after owner exit/reopen; start requires prior stock
consumption. Generic journal append cannot write the private event. Legacy
histories without stock markers remain readable; malformed stock events on
legacy claims are rejected. Readers/writers must deploy coherently: older readers
cannot validate the new scoped claim/event; no history migration is performed.
The earlier synthetic-model-allowance prototype has a different fixed profile
and grants no authority for this route; it is not copied as a second ledger.

A successful retained stock child must pass the same strict artifact validator.
The returned bounded receipt bytes are rechecked against the validated hash,
preventing replacement between validation and publication. Every result remains
synthetic/process-only and `not_admitted`, with no scientific run/D1 completion
invented. Internal dispatch now executes this fixture; production registration,
actual provider/subscription/token/USD enforcement, CPU caps, full installed
runtime integrity, arbitrary-descendant containment and full project qualification
remain separate gates. No live inference or other-host work is part of this slice.

## Typed stock-worker boundary successor

[Worker hardening](../../docs/operations/native-worker-hardening.md) records targeted
Python3.11 stock-runtime typing separately from the lighter conformance environment.
Its closed request/audit/context/result checks keep the exact native RDLoop and the
existing three-file worker manifest. Changed bytes require freshly derived profiles;
old approvals/history are not rewritten. Synthetic execution remains unqualified for
live inference, scientific admission or hard budget enforcement.

## Model gateway (2026-11-14)

`model_gateway.py` is the one way RD-Agent reaches an AI model
([ADR-0044](../../docs/adr/0044-rdagent-model-gateway.md)). It is a stdlib-only program, run with
any Python 3.11 or 3.12, that listens on `127.0.0.1` only and speaks the OpenAI chat-completions
and embeddings formats; it imports neither ALPHA nor RD-Agent. Chat goes to the signed-in Codex
CLI (`codex exec`, confined: read-only, ephemeral, no user configuration, no tools, no web search,
RD-Agent's system message in place of Codex's built-in instructions), embeddings to local Ollama
`nomic-embed-text`, and an optional paid route to an OpenAI-compatible provider whose key the
owner sets in the environment. The fixture loops above still clear every model setting; nothing
here changes them.

```sh
python3 workers/rdagent/model_gateway.py serve --data-dir /absolute/data/dir --run-id <id> \
  --accept-unhonoured temperature          # writes model-gateway/session-<pid>.json and session.json
python3 workers/rdagent/model_gateway.py status --data-dir /absolute/data/dir
```

RD-Agent is pointed at it with `CHAT_MODEL=lm_studio/alpha-chat`,
`EMBEDDING_MODEL=lm_studio/alpha-embed`, `LM_STUDIO_API_BASE=<base_url>/v1`,
`LM_STUDIO_API_KEY=<token>` (both from the session file, a per-start local token, mode 0600; the
launcher reads `session-<pid>.json`, so runs that share one state folder, and so one monthly cap,
can start together; `session.json` names the latest gateway and is removed only by it) and
`LITELLM_LOCAL_MODEL_COST_MAP=True` (otherwise LiteLLM downloads its price list at import). The
`lm_studio/` prefix is LiteLLM's generic OpenAI-compatible provider: unlike `openai/<unknown
name>` it forwards `response_format`, so the gateway can enforce RD-Agent's JSON mode.

- **Fidelity:** each request parameter is honoured, enforced another way (JSON checked and retried;
  a JSON schema passed as `--output-schema`; streaming replayed after the whole reply), waived only
  if listed in `--accept-unhonoured` (and then recorded on every call), or refused with an
  OpenAI-shaped 400 naming it. On the Codex route `temperature`, `top_p`, `seed`, penalties and
  `max_tokens` cannot be honoured; RD-Agent always sends `temperature` 0.5, so its launch accepts
  losing that one. Tools, `stop`, `n`>1, images and unknown keys are always refused.
- **Budget:** `--run-max-calls` (60), `--month-max-calls` (3000), `--run-max-usd` (10) and
  `--month-max-usd` (50, the owner's ceiling, cannot be raised) are checked under a file lock before
  every model attempt and fail closed. State: `<data-dir>/model-gateway/budget.json`; the data
  directory may not be inside a git tree; unreadable state refuses every call.
- **Records:** `<data-dir>/model-gateway/calls.jsonl`, one line per request (route, real model,
  effort, honoured/enforced/waived/refused, attempts, JSON validity, tokens, dollars, time, status,
  prompt and reply hashes). No prompt or reply text unless `--log-content`.
- **No silent switch:** a Codex usage limit returns `codex_usage_limit` (429); the paid route is
  used only when the gateway is started with `--chat-route api` and the owner's
  `ALPHA_GATEWAY_API_BASE`/`ALPHA_GATEWAY_API_KEY` plus `--api-model` and both prices.

Checks: `uv run pytest -q tests/unit/test_rdagent_model_gateway.py` (no sockets, fake `codex`) and
`uv run python scripts/run_owned_test.py -- uv run pytest -q -m smoke -n 0
tests/smoke/test_rdagent_model_gateway_smoke.py` (loopback only; with `ALPHA_RDAGENT_SOURCE` and
`ALPHA_STOCK_PYTHON` set it also drives RD-Agent's own `APIBackend` through LiteLLM against the
fake route). Measurements: [the task's verification](https://github.com/tradingsystem1880-eng/Project-ALPHA/blob/pre-thin-2026-11-14/docs/work/archive/2026-11/2026-11-14-rdagent-model-gateway/04-verify.md).
It is not part of `scripts/setup.sh` or `gate.py doctor`: it needs no install, and whether Codex is
signed in is already what `codex login status` reports.

## ALPHA-judged factor loop (2026-11-14)

RD-Agent's own factor loop (`rdagent.app.qlib_rd_loop.factor`, unmodified) with ALPHA as the
judge ([ADR-0049](../../docs/adr/0049-alpha-judges-rdagent-factors.md)). RD-Agent proposes and
codes factors; its settings `QLIB_FACTOR_SCEN`, `QLIB_FACTOR_HYPOTHESIS_GEN`, `QLIB_FACTOR_RUNNER`
and `QLIB_FACTOR_SUMMARIZER` name four classes in `alpha_factor_judge.py`; the runner sends the
factor values to `alpha_cli.rdagent_factor_eval` in ALPHA's environment, which screens each new
factor at daily (1-day), weekly (7-day) and monthly (28-day) holding clocks. Decision days
start at 2021-01-01 and advance by the clock's calendar days; screens use non-overlapping
next-open-to-open forward returns ending by 2023-12-31, autocorrelation-adjusted inference and
seeded stationary-bootstrap intervals. Fewer than 20 observations carry a low-sample warning.
BH counts every factor x clock as a trial across runs; V1, V2 and imported historical results
each count once at daily. Records disclose both trial count and distinct factor count.
Only clocks with q < 0.10 replay through ALPHA's canonical synchronized engine. Replays choose
the top third on clock decision days, then drift holdings by closes between rebalances. Small
residual trades caused by fill prices and fees are executed and charged. Costs remain 10 bps
fee plus 6 bps slippage per side; annualisation uses 365 days. Each clock reports net/gross
metrics, turnover per day, total daily turnover divided by scheduled rebalances (including the
initial allocation), annual cost (total fees and slippage divided by mean canonical equity,
annualised over the replay days), and rebalance count. The engine's final liquidation is
charged and included in turnover and costs.

Only a weekly or monthly PASS (q < 0.10 and positive net annual excess) makes a CANDIDATE.
A daily-only pass is FAST_ONLY and ALPHA's decision remains false. New evaluations write one
V3 ledger row per factor with all three clock results; top-level screen/replay/p/q mirror daily.
The lead is the lowest-q passing swing clock, otherwise the lowest-q clock; RD-Agent's legacy
IC uses that lead. The legacy result also includes `<factor>.<clock>.status`, `mean_ic`,
`q`, `net_annual_excess` and `mean_turnover`, plus `<factor>.feedback` with the explanation.
Deflated Sharpe counts every replayed factor x clock. Repeated code hashes
are not evaluated again. The proposer receives the plain-English swing brief on every context
call, before the cross-run ledger summary, including when no ledger exists. It asks for slow,
low-turnover signals with a mechanism and falsifier, explains the daily ideas that failed
after costs and the slow ranks whose held top third lost before costs. The summary lists the
newest distinct factors (at most 30) as whole lines within 4000 characters, rounds IC and q to
three decimals, gives each replayed clock's annual return before and after costs, its annual
cost and daily turnover, and states how many older factors it left out (2026-11-16: it had cut
the 23rd line in half and showed no replay numbers). All results remain exploratory, not admitted.

Spread check, idea families, universe file and call limit
([ADR-0055](../../docs/adr/0055-spread-check-family-brief-and-universe-file.md), 2026-11-16):

- Before a screened clock (q < 0.10) is replayed, the evaluator checks on the same decision days that
  the top third the factor would hold beat its bottom third before costs (mean over decision days,
  positive under both tie orders). If not, the clock is `SPREAD_FAIL`
  (`top-third-does-not-beat-bottom-third`) whatever its replay shows. Each screened clock records a
  `spread` object: top- and bottom-third mean returns, spread per hold and per year, t-statistic
  (autocorrelation-adjusted), bootstrap interval, decision days, the share of the top third replaced
  per rebalance and the yearly cost that implies. A stricter gate, never a pass. A spread-stopped
  clock, or one whose spread could not be computed (`ERROR`), is still replayed (marked
  `counted_only`) so the Deflated Sharpe counts every screened clock as a trial, exactly as before
  the check; feedback and RD-Agent's result keys show such a replay as "counted only, not a
  result", never as returns. A universe hash in the panel receipt requires the file.
- Embeddings: after the local service refuses an input (HTTP 400), the gateway retries once with
  inputs over `--embed-max-chars` (2,000) split at sentence ends and averages the pieces' vectors
  (logged as `chunked_inputs`, `chunks`); never truncated. If it still fails, the coding step
  leaves that memory entry out (`memory-skips.jsonl`) and the receipt counts
  `memory_entries_skipped`; `call_split` adds `chunked_embedding_inputs` and `embedding_chunks`.
- The proposer's context starts with every idea family in the ledger (name-keyword groups: tries,
  best result, failures by status), names the families with `--family-switch-after` (3) or more
  failed tries and no candidate, and tells it to move to a different family. Ledger lines add the
  spread numbers for every clock that reached the check.
- `--universe /abs/file.json` freezes the panel with a universe file (`AlphaRdagentUniverseV1`,
  examples in `universes/`): source, instruments, a point-in-time liquidity rule, calendar (which
  fixes the year length and clocks) and minimum universe. The file and its hash are bound into the
  panel receipt; an unbound or edited file is refused. `binance-spot-liquid.json` (90-day median
  quote volume of at least USD 1 million, at most 50 coins) keeps all 15 coins of the local store on
  every exploration day; widening needs more coins in the store. `alpaca-us-stocks.json` is refused:
  the Alpaca store has 9 single stocks (and 6 funds), fewer than 15, and the exchange-session
  calendar is not yet evaluable.
- Gateway: `--api-timeout` (180 s) bounds each paid call in total; a slower call ends as
  `provider_timeout`, and it or an empty reply is retried `--provider-retries` times (1); every
  attempt counts toward the caps. The receipt's `call_split` separates model chat calls (requests,
  attempts, dollars) from free local embedding calls, with provider timeouts, empty replies and
  retries.
- Measured 2026-11-16: offline, on the 18 factor × clock trials that had reached the replay, the
  spread check rejects 16 (all 15 that lost before costs and one daily-only pass); no model calls.
  Two fresh runs (DeepSeek V4.1 Flash, 3 loops each, USD 0.085 and 0.138): 11 factors judged, 3
  passed the rank screen, 1 passed the spread check (daily-only), none a swing candidate. Proposals
  moved from "price near its high" to intraday/overnight drift, return predictability, trend
  efficiency, co-skewness and drawdown. Five calls hit the 180 s limit; four retries succeeded, one
  request failed after two attempts and the run went on. Run 2 stopped in its third loop because
  local Ollama refused a 7,394-character embedding (HTTP 400), not a model timeout; its receipt was
  written. Embeddings were 21 of 60 and 16 of 47 counted calls. RD-Agent never sees 2024 or later; no Qlib model, Docker
image, MLflow or conda is involved.

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

### Research memory (2026-11-15)

Memory is enabled by default. RD-Agent keeps CoSTEER's working factor programs and failed
coding attempts, and continues the previous run's hypothesis, experiment and feedback trace.
It uses RD-Agent's supported knowledge settings and session checkout; earlier run folders stay
unchanged. This is working knowledge: ALPHA's trial ledger remains the sole evidence authority.
Nothing is copied between memory and the ledger.

ALPHA's code-level verdict reaches coding memory before evaluation: factors that fail the
look-ahead or reproducibility check (`LOOKAHEAD`, `UNSTABLE`) or run but return the wrong output shape (`FAILED`) lose their
successful coding-reference status. Their graph nodes become `alpha_rejected_implement` and
their attempt history stays available for inspection. Screen and replay failures keep their
correct implementations as coding references. The coder reloads shared knowledge before each
experiment under the same file lock. Signed knowledge updates replace the file atomically;
demotion errors are recorded without stopping the run.

`coder-verdicts.jsonl` records each rejected factor's iteration, name, code and task-information
hashes, status, whether it was demoted, and any memory error. With memory disabled, it records
`demoted: false` and `no persistent coding memory`. The inspector lists these task names as
“ALPHA rejected the code of: ...”.

The default location is `research-memory/` beside the trial ledger. Use `--memory-dir /abs/path`
to choose another location outside every git work tree, or `--no-memory` to run fresh without
reading or writing memory. `--coder-max-loop` accepts 1–3 (default 2); at 1 the coder cannot learn
an error-to-fix lesson within a run. The gateway's 60-call cap still applies.

`memory.json` links sessions by path and records runs, hashes and warnings. CoSTEER writes
`costeer/factor-knowledge.pkl`. The signing key lives at `signing/artifact_signing.key` (mode
0600): it is an integrity key, not a credential. Keep the memory directory and linked run folders
available together.

Unreadable manifests, changed RD-Agent versions and unloadable coding knowledge are quarantined
with a reason. Missing or unloadable sessions start a fresh trace while keeping usable coding
knowledge. A changed ALPHA judge produces a warning and continuation still proceeds. Warnings
appear in the run receipt; entry-side events are in `memory-events.jsonl`. If a gateway secret is
found, the knowledge file is deleted and the new session is excluded; the warning names any
session files left for the owner to delete. A recording failure is also reported in the receipt.

Inspect without changing memory (omit `--json` for a plain-English explanation):

```sh
.venv/bin/python workers/rdagent/research_memory.py show \
  --memory-dir /abs/runs/rdagent-trial-ledger/research-memory \
  --trial-ledger /abs/runs/rdagent-trial-ledger/rdagent-factor-trials.jsonl --json
```

Set `ALPHA_FACTOR_PYTHON` and `ALPHA_RDAGENT_SOURCE` to inspect coding attempts, errors, working
programs and research rounds alongside the ledger's verdicts. Without that runtime the inspector
shows manifest facts and explains what is missing. It copies the integrity key into a temporary
HOME for reading signed artifacts and removes the copy afterwards.

A continued run starts at a round boundary (2026-11-17). It loads only a completed round's
checkpoint (`<loop>/4_record`; if that dump is truncated, an older completed one), takes the
research trace (hypotheses, experiments, feedback) from it, and runs it in a fresh RD-Agent
scheduler built from this run's settings, so this run's own round folders are numbered from 0.
A round the previous session left half-finished (the call cap stopped it) is not resumed: it is
appended to that run's `rounds.jsonl` as `AlphaRdagentRoundAbandonedV1`, status
`abandoned_at_cap`, `trial_created: false`, and no trial is invented for it; this run's own
unfinished round is recorded the same way when it ends. The receipt's `rounds_completed` counts
this run's completed rounds and `loops_after` = `loops_before` + `rounds_completed` (only this
run's rounds when the previous session could not be loaded). The model calls already spent on
an abandoned round stay spent, and its proposal is not re-proposed or evaluated.

The context and feedback system prompt end with a current-universe correction derived from this
run's frozen receipt and universe, including its instrument count and declared survivorship.
They refuse missing or unreadable information before any proposal call; the restored pickle stays
unchanged. Universe prose declaring `N later delisted` (or explicit inclusion of delisted names)
feeds the new receipt and row's `universe_includes_delisted` flag. Early endings alone do not
establish delisting. A prose count must describe the selected run, not the store's original size;
an impossible count refuses the freeze. Explicit inclusion without a count says it is not recorded.

Known limits: a run that crashes before finishing a round keeps the previous session as the one
to continue. Two runs started at the same time from one memory both continue the same session
and the later one becomes the pointer; the coding knowledge itself is shared safely through
RD-Agent's file lock. The restored research trace keeps RD-Agent's pickled scenario description
from its first run (the data folders and the coder come from the current run). RD-Agent's own
logs from a memory run are signed with the memory key, so its log viewer needs
`ARTIFACT_SIGNING_KEY_PATH` pointed there.

### Failure reasons, idea families and the call split (2026-11-17)

A factor that produced no usable values is a `FAILED` trial with a `failure_reason`, carried into
its ledger row, `alpha ledger list` and the next proposal's feedback: `critic_rejected` (the code
ran; RD-Agent's critic did not accept it), `cap_reached` (the call cap stopped the coder),
`exception` (the code raised; `failure_detail` keeps the error's own line, never the traceback
header) or `bad_output` (no `factor.py`, or not one numeric column on a date/instrument index).

Each factor row also keeps the proposal's `description`, `formulation` and `variables`. The idea
family rule (`--family-switch-after`, ADR-0055) classifies a composite (machine learning, a
regression, a weighted combination) or a factor whose name has no family keyword by the feature
families its own words name; it inherits every one, so a ridge composite of volatility, drawdown,
skew and autocorrelation features counts as a try in each, and it is barred when any of them is
closed. Only evaluated screen, spread and replay failures (including daily-only passes) count
toward closing a family; code failures remain trials but do not close families. Before coding,
`research_memory` wraps the current coder with `FamilyGuard`: a closed-family proposal is refused,
with the closed and open families named. It records `refused_closed_family` as the reason for a
`no_admissible_idea` round, `trial_created: false`, and sends that message to the trace without a
feedback-model call. The wrapper ends the round using upstream's skip exception. Same-round
re-proposal is not implemented; the pinned upstream scheduler integration needs an outside check.
A composite with no identifiable input is `composite: unknown inputs` (older ledger rows
carry no description, so the 2026-11-17 `ml_ridge_*` rows sit there), itself subject to the
limit. The match is approximate and over-inclusive: a stray family word adds a family, never
removes one.

The default `--embedding-route local` uses the same Ollama requests and long-input retry as
before (`ollama` remains a legacy spelling; `fake` is for tests). Select
`--embedding-route provider --provider-embed-model MODEL --provider-embed-usd-per-mtok PRICE`
to embed whole inputs through the paid chat provider's `/embeddings` endpoint. Model and positive
USD-per-million-token price are required; neither has a guessed default. `ApiChat.__init__` in
`model_gateway.py` and `ProviderEmbeddings.__init__` in `gateway_embeddings.py` read the same
`ALPHA_GATEWAY_API_BASE` and `ALPHA_GATEWAY_API_KEY`; only the gateway process receives them.
Provider inputs are never split. Explicit input refusals are skipped with their original cause;
a budget refusal stops the worker immediately as `BudgetExhausted`.

Both built-in embedding routes are exempt from the 60-call and monthly call counts. Their
combined attempts, including local chunk retries, have a per-run guard of 2,000
(`EMBEDDING_CALLS_PER_RUN`); exceeding it returns `budget_exhausted`. The exemption is decided in
`gateway_embeddings.embedding_attempt` from the actual backend and route, never caller fields
or model aliases. Unknown injected backends stay counted. Chat and chat retries remain counted;
the 60-call, USD 10 per-run, USD 50 monthly, 3,000 monthly-call and 180 s paid-call limits keep
their values. Provider embeddings reserve characters / 3 × price before sending, then settle
using reported total tokens (prompt tokens if total is absent). Missing usage keeps the estimate.
An explicit error with no usage or an unavailable connection settles to zero; a timeout or
unreadable reply retains the estimate because the request may have been billed. No embedding
retry is made on the provider route.

`call_split` and the receipt report `local_embedding_calls`, `provider_embedding_calls`,
`provider_embedding_usd` and `provider_embedding_tokens`, plus route and model. Receipt totals
come from the reserved budget, even if a call was not logged; unavailable totals are null.
`calls` and `counted_toward_call_cap` remain compatible aliases for counted calls. Old budget
files, call logs and receipts keep historical counts unchanged. Token totals count only usage
actually reported by the provider; unknown usage is not invented.

The wrapper's `embedding-models.json` sidecar binds each graph entry's text hash, model id,
dimension and vector. On the coder's first use, unknown or different-model entries are embedded
through the gateway before retrieval. Compatible vectors are reused; upstream's model-agnostic
embedding cache is bypassed for queries and new nodes. Failed entries are hidden for this run,
retained for a future attempt, and logged in `memory-skips.jsonl`. Re-embedding events go to
`memory-reembedded.jsonl`; the receipt counts `memory_entries_reembedded`. Malformed sidecars
fail loud. Unknown legacy entries are re-embedded before their first retrieval.

### Compare embedding retrieval

`embedding_eval.evaluate(entries, queries, embed)` accepts a deterministic callable for offline
checks, and reports macro recall at 3 and 5, mean reciprocal rank, refused inputs and split
inputs. Refused queries score zero; refused relevant entries stay in recall denominators.
Cosine ties use entry ids. Invalid vectors fail loud. Run once per gateway/model on the same set:

```sh
.venv/bin/python workers/rdagent/embedding_eval.py --entries /abs/ideas.json \
  --queries /abs/queries.json --gateway-url http://127.0.0.1:PORT
```

Supply the gateway session token through `ALPHA_GATEWAY_SESSION_TOKEN`, never the provider key.
Entries are a JSON list with `id` and `text` (plus `idea_family` and `outcome` when labelled);
queries contain `text`, `relevant_ids`, and optional `exclude_ids`. The harness asks the gateway
for optional `report_embedding_stats`; ordinary embedding responses remain unchanged.
`build_labelled_set(ledger, memory)` joins explicit labels by `id` or `code_sha256`; `--ledger`
accepts JSONL instead of `--queries`. Labels require an explicit idea family and symbol list
(`symbols` or ledger `instruments`). Same-family entries with identical symbol sets are relevant
to each other, excluding self matches and ignoring outcomes. The output calls this a proxy,
not ground truth; missing family labels must be supplied before using a raw ledger.

`--coding-reasoning-tokens` exists but must stay unset: OpenRouter documents `reasoning.max_tokens`,
but whether the pinned model's providers honour it (the gateway sends `require_parameters`) is
unconfirmed without a paid call, and the gateway cannot yet tell a coding call from others, so
any value is refused.

### RD-Agent's own log viewer (2026-11-15)

RD-Agent's unmodified Streamlit log viewer shows each loop's hypothesis, the generated code
per evolve step, feedback, and ALPHA's numbers in RD-Agent's result fields. ALPHA has no
information ratio, so that field is empty.

```sh
bash scripts/setup_rdagent.sh --with-ui
# Set ALPHA_VIEWER_PYTHON and ALPHA_RDAGENT_SOURCE to the exports printed by setup.
.venv/bin/python workers/rdagent/rdagent_viewer.py serve --run-dir /abs/runs/<date>-<slug>
```

Setup is needed once: the pinned Python 3.11 viewer runtime contains 191 packages, about
1.1 GB. The launcher verifies its recorded profile before starting. Open
http://127.0.0.1:19899; it listens on 127.0.0.1 only and stays in the foreground until Ctrl-C.
Use `--port` to choose another port if that one is busy.

Repeat `--run-dir` to view several runs. Each must be absolute, outside git and contain
`work/log/`. The launcher creates symlinks in `rdagent-viewer-links/` beside the first run
(or `--links-dir DIR`, also outside git); it removes only old symlinks and leaves other files
alone. Runs sharing one enabled research memory use that memory's signing key. A single run
otherwise uses its own home key; for other combinations supply `--signing-key PATH`.
One viewer can read only one signing key. The key is copied into a temporary HOME, removed
when the viewer exits; model settings and API keys are excluded from its environment.

Runs from before 2026-11-15 lack the result field the viewer reads and stop it with a
`KeyError`, shown in the page.

### Evidence recorded per trial

All files below live under the run directory, outside git; they remain exploratory, not admitted.
Series include a `clock` column; replay and holdings files have one block per replayed clock.

- `evaluations/iter-<n>/series/<code_sha256>.screen.parquet`: per-clock rank IC and finite-name counts.
- `evaluations/iter-<n>/series/<code_sha256>.buckets.parquet`: direction-adjusted tercile outcomes and observation counts.
- `evaluations/iter-<n>/series/<code_sha256>.buckets_daily.parquet`: outcomes per day and tercile (bucket 3 is the replay's top third).
- `evaluations/iter-<n>/series/<code_sha256>.replay.parquet`: canonical period returns, turnover, fees and slippage.
- `evaluations/iter-<n>/series/<code_sha256>.holdings.parquet`: decision-day instruments, target weights and scores.
- `evaluations/iter-<n>/series/series.json`: factor hashes and file hashes, bound into evaluation inputs and trial-ledger evidence references; unavailable series carry `series_note`.
- `code/<code_sha256>.py`: the exact factor code, written once and checked on reuse.
- `rounds.jsonl`: RD-Agent's hypothesis, tasks and feedback words linked to factor hashes and both decisions; `feedback.jsonl` stays unchanged.
- `steps.jsonl`: UTC start/end records for each loop step, including error types.
- `calls-labelled.jsonl`: this run's gateway calls labelled by loop and step; `launch.jsonl` also records launcher step starts.
- New trial-ledger rows carry a deterministic plain-English `plain_name` beside the original name.

### Human-authored rule families

```sh
.venv/bin/python -m alpha_cli.rdagent_rule_family run \
  --spec /abs/spec.json --spec-sha256 <sha256> --data-dir /abs/data \
  --run-dir /abs/new-rule-run --ledger /abs/rdagent-factor-trials.jsonl
```

- Copies the frozen `spec.json` and `spec.sha256` into the new run directory outside git.
- Writes `trials/<symbol>-N<N>/series.parquet`, `trial.json`, and each book's `fills.parquet`.
- Writes `family-result.json` with within-family BH, outcomes, warnings and exploratory labels.
- Appends one block of rule trials to the shared ledger and writes `receipt.json` with hashes and indices.

Optional instrument defaults are 0 fee / 5 bps slippage, 252 periods per year, CASH for
non-crypto and MARGIN for slash pairs; each default is a warning. Reads stop at 2023-12-31.
Rule trials count in the ledger total but do not enter RD-Agent's factor family or proposal summary.

Unknown ledger schemas are skipped by the proposer with a counted explanation. The evaluator
keeps their trial indices contiguous, excludes their contents from identity and repeat checks,
and counts each as one conservative trial with p = 1.0. Evaluations containing such rows add
`ledger_unknown_rows` (count and distinct schema names) and warn on stderr. Malformed complete
lines and malformed known-schema rows still fail loud. The proposer, which reads without the
ledger lock, ignores a final line without a newline (another writer may be appending); the
evaluator, the exposure command and the rule family read under the lock, so for them a partial
last line means a crashed writer and they fail loud rather than append after it.

### Exposure log and imported trials

```sh
.venv/bin/python -m alpha_cli.rdagent_exposure add \
  --ledger /abs/runs/rdagent-trial-ledger/rdagent-factor-trials.jsonl --file /abs/exposures.json
.venv/bin/python -m alpha_cli.rdagent_exposure list \
  --ledger /abs/runs/rdagent-trial-ledger/rdagent-factor-trials.jsonl --json
.venv/bin/python -m alpha_cli.rdagent_factor_eval import-historical \
  --ledger /abs/runs/rdagent-trial-ledger/rdagent-factor-trials.jsonl --file /abs/historical-trials.json
```

`add` appends validated disclosures to `rdagent-exposure-log.jsonl` beside the trial ledger,
outside git; its input is a JSON list without `schema`, `entry_index` or `label`, and duplicate
content refuses the whole call. `list` writes nothing and shows the entries and each trial's
current exposure label (`--json` for canonical JSON, omit it for plain text). `import-historical`
appends V2 `IMPORTED` trials with hashes of the supplied absolute `code_path` files and their
original windows and provenance; they count in the distinct-code family with p = 1, are never
evaluated or replayed, and later identical code is a `REPEAT`.

An exposure matches when its end date reaches the trial's reserved start, its case-insensitive
Python regex matches the factor name, and its matching instruments overlap the trial's
instruments (or are `["*"]`); legacy trials use the 15-coin loop universe. Matching `known` or
`suspected` exposures mark the protected window previously exposed and unable to give fresh
confirmation; `unknown` stays disclosed, and a missing log leaves exposure unknown.

Choosing the model route (owner decision 2026-11-14: DeepSeek through OpenRouter is allowed for
RD-Agent, with temperature control; caps unchanged at 60 calls and 10 USD a run, 50 USD a month):

- **Codex (default, no cost):** as above. `temperature` is waived and recorded on every call.
- **DeepSeek through OpenRouter (paid, honours temperature):** model
  `deepseek/deepseek-v4.1-flash-1017` (DeepSeek V4.1 Flash, 17 October 2026 snapshot served by
  DeepSeek; 1,048,576-token context; OpenRouter lists `response_format`, `structured_outputs`,
  `temperature` and optional `reasoning` for it), USD 0.038 per million input and 0.50 per
  million output tokens (cache reads 0.01), read from https://openrouter.ai/api/v1/models on
  2026-11-14 12:35 UTC. Chosen over the undated `deepseek/deepseek-v4.1-flash` (0.0507 / 0.2028)
  because a dated snapshot cannot change under a run; re-read the prices before each use.
  `--api-openrouter` makes OpenRouter route only to providers that honour every parameter sent
  (`provider.require_parameters`) and settles the budget with the cost OpenRouter reports
  (`usage.cost`, recorded beside the gateway's own estimate as `estimated_usd`). The key reaches
  only the gateway process: load the owner's file inside the same command, never print it.

```sh
bash -c 'set -a; . ~/.config/alpha/openrouter.env; set +a; exec .venv/bin/python \
  workers/rdagent/factor_loop_launch.py run --chat-route api --api-openrouter \
  --api-model deepseek/deepseek-v4.1-flash-1017 \
  --api-price-in-per-mtok 0.038 --api-price-out-per-mtok 0.5 \
  --data-dir ... --run-dir ... --gateway-data-dir ... --trial-ledger ... --run-id ... --loop-n 2'
```

  First run 2026-11-14 13:04-13:13 UTC (run `rdloop-deepseek-20261114-1`, 3 iterations): 54
  calls of 60, USD 0.044 as reported by OpenRouter (gateway estimate 0.039), every reply valid
  on the first attempt, temperature honoured. Nine factors entered the ledger (trials 6-14),
  mostly short-term reversal: five failed the screen, one failed to run, three passed the screen
  and failed the replay after costs (daily turnover 0.52-0.79). No candidate. One run per route
  is not a quality comparison.
- Prices change: re-read 2026-11-16, the same snapshot lists USD 0.15 / 0.60 per million (weekday
  windows at 0.30 / 1.20), and OpenRouter charged up to twice the gateway's estimate on one call;
  the budget settles on the charged cost, so caps hold. Four system-test runs that day (one with
  memory, three without, comparing `deepseek/deepseek-v4-pro-0813` at 0.111 / 4.44 and
  `deepseek/deepseek-v4-flash-0731` at 0.06 / 0.18) cost USD 0.66 in all, judged 18 factors and
  found no candidate. Two runs stopped at the 60-call cap during coding (free local embedding
  calls counted toward it at the time), one after a stuck call; replies that reason for 8-12 minutes and return
  no text (`invalid_provider_response`) occurred in every run.
- Embeddings default to local Ollama independently of chat; the provider route is opt-in above.
- Not yet: supervision by `alpha`'s native job supervisor
  ([backlog](../../docs/roadmap/backlog/rdagent-factor-loop-supervision.md)); a Nautilus replay;
  the candidate-to-research-case hand-off
  ([backlog](../../docs/roadmap/backlog/rdagent-candidate-to-research-case.md)).

### Missing bars and causal membership

New panel receipts carry `AlphaRdagentGapPolicyV1`. `_rdagent_membership.panel_summary`
records first/last dates, missing days inside each span, longest gaps and early endings;
these are descriptions of the frozen input, never trading signals. The universe may provide
an optional absolute `data_dir`, which must exist when the panel is frozen (a frozen run
still loads after the store moves); otherwise the launcher's data
directory applies. This does not change the gateway, ledger or other ALPHA data directories.
No wide-universe instrument list is supplied by the code.

A name can rank only after `REENTRY_BARS = 20` consecutive daily bars, with a finite factor
value, and passing any configured liquidity rule. A gap resets the streak. Days below the
existing five-name minimum are skipped and counted. Factor input gives every instrument null rows
from the first data day (no later than the first cut) until it lists, and null rows for missing days
inside its span; no row follows its last bar and nothing is forward-filled. Every cut therefore keeps
the full panel's instrument columns.

Held names with missing bars stay at their last close and cannot finance other purchases.
They exit at the first resuming close, with the usual sell costs, or are written off after
`WRITE_OFF_AFTER_DAYS = 30` calendar days without a bar. The write-off recovers last close
multiplied by `1 - DELISTING_HAIRCUT`, where `DELISTING_HAIRCUT = 0.30`.
**This 30% loss is a conservative assumption, not a measured delisting recovery.** An unresolved
position at panel end uses the same assumption, counted separately as `written_off_at_panel_end`.
An administrative write-off has no fictitious exchange fee. A later resumption can become a
new position only after a fresh warm-up. The zero-cost comparison basket follows the same waits.

Ordinary screen labels retain the fixed next-open/open horizon. A missing endpoint uses the
first available close within 30 days after the endpoint, otherwise the last close with the
haircut. A label whose entry open is missing is zero (the order never fills). Unresolved labels whose search reaches the reserved boundary remain null. Spread
holdings instead follow the position waiting rule, including gaps inside a holding period;
a missing entry open is uninvested cash. Both kinds of fallback are counted separately.
The report and proposer feedback state early endings, missing instrument-days and position
haircuts, with per-clock counts for spread legs and replay positions. Replay events and daily
position/cash snapshots are persisted with the diagnostic series.

Receipts without a gap policy retain the earlier evaluation path; they remain readable and
are never rewritten. Gap-free, warmed-up panels preserve the old screen, spread and replay
numbers, checked against the retained canonical replay path. Costs, clocks, thresholds, trial
counting and the reserved window are unchanged. A month whose only quality warning is its
cadence gap is accepted at freeze; any other warning or failure still refuses the panel.

### Identity breaks across a gap

The wide store may be used once every implausible jump is declared. Freeze enforces this only
across any gap of one or more missing days (below); jumps between consecutive daily bars are not checked.
The owner supplies `identity_breaks` in the universe file, a list of entries with `instrument`,
`new_from` (a `YYYY-MM-DD` date) and `reason` (`ticker_reused` or `redenominated`). The instrument
must belong to the universe and its dates must be strictly increasing. No real break list is
shipped in code; the tiny examples in `test_rdagent_identity_breaks.py` are synthetic.

A `redenominated` entry additionally requires a finite positive `ratio`: new price units per old
unit, so 100 when the first new price is 100 times the last old one (DREP 0.026288 then 2.629).
Freeze divides OHLC on or after `new_from` by this ratio and multiplies base volume by it; quote
volume is unchanged. The instrument keeps its identity and normal gap handling. Earlier prices
are untouched. Old declarations without a ratio refuse with an instruction to add it; old frozen
receipts remain readable. Each applied rescale is listed in `identity_rescales` with name, date and ratio.

For `ticker_reused`, freeze renames rows on and after each boundary to `<INSTRUMENT>~2`, then
`~3`, counting ticker reuse only. Each row belongs to one identity; generated-name collisions
are refused. Old identities follow the waiting and haircut rules; new identities earn their own
warm-up. Future declarations change no earlier trading decisions. Declarations beyond the panel
remain in the universe but are not listed as applied.

After rescaling and relabelling, `_rdagent_identity.check_jumps` checks every remaining interior gap with at
least `IDENTITY_JUMP_MIN_GAP_DAYS = 1` missing calendar days (excluding the two observed days).
If resume close / last close is above `IDENTITY_JUMP_RATIO = 5.0` or below `1 / 5.0`, freeze
raises `IdentityJumpError`; one refusal names every such jump with its instrument, both dates,
both closes and their ratio. There is no override. Even a genuine large move across such a gap
must be declared by the owner as a break or the instrument must be left out.

Known limit: a jump between consecutive daily bars (no missing day) is deliberately not checked, so a genuine crash never refuses a freeze.
Exchanges often pause a pair for a few days to swap a redenominated token, so such a jump
passes freeze and, held across the pause, is booked as a real move unless the owner declares it.
Check the store for short-gap jumps before relying on it; a consecutive-day check would also
flag genuine crashes, so neither has been added without an owner decision.

The panel receipt records applied ticker splits with `new_name`, and `identity_jump_policy`
(`min_gap_days`, `ratio`). Reports and proposer feedback state the number of distinct tickers
split. Old frozen receipts remain readable; no-break panels retain their bytes and
numerical results. New receipts add the identity metadata and new reports add the count; source
fingerprints still change when code changes. Serializing HDF in the isolated factor runtime
still needs an outside check.

### Reproducibility and plain feedback (third loop fix-up)

Prefix comparisons retain the first mismatching cut, row date, instrument and absolute difference
(null for missing keys or non-finite values). A mismatch triggers exactly one fresh execution on
an identical copy of the truncated input. A second differing answer is `UNSTABLE`; reproducible
truncated output that differs from the full run stays `LOOKAHEAD`. Both remain invalid trials,
counted exactly as before, and neither can be the lead factor. Unavailable checks retain their
existing classification and record the error; they never demote coding memory. Fixed cuts do not prove
absence of leakage between cuts; numerical instability is diagnosed, not repaired.

Each factor records a write-off count across its evaluated clocks and a sentence naming up to
five coins (then “and N more”), including the assumed loss. The feedback writer appends it even
if the model omits it; proposal ledger lines keep the count. Spread figures are shown only for
clocks that passed the rank screen. Replay output calls its old `missing_coin_days` metric
`unrankable_instrument_rebalances`: instrument observations without a finite eligible rank on
scheduled rebalance days, distinct from missing bar days in the receipt. Readers accept the old name.
