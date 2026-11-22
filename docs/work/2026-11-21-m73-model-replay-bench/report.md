# Report: model replay bench (m73)

## Answer first
The bench commands are built and tested with a fake model client. Two parts of the brief could not be built:
both live in `workers/**`, which the common rules protect. No real model was called.

## What was built
1. `alpha rdagent bench plan|run|report` (`rdagent_bench_cmds.py`, `_model.py`, `_score.py`).
2. `plan` prints the call count and cost from recorded token counts and your prices. It refuses over 60 calls, 10 USD per run, 50 USD per month.
   It writes and calls nothing. A missing price or token count refuses the plan.
3. `run` stores each output once (exclusive create), so a rerun resumes. It has no ledger or memory option. The store must be outside git.
   The fake client (`--fixture`) needs no network. The real client posts to one local gateway per model; each gateway's token comes from `ALPHA_BENCH_TOKEN_<MODEL>` (see round 6).
4. `report` shows, per model: refusal rate, buildable share, cost per call, median latency. It shows the within-prompt difference per pair
   with the prompt count, and a plain sentence on what 30 pairs can show. No winner label. A missing value shows its reason.
5. Docs: tool card `research/tools/rdagent-model-bench.md`, a section in `rdagent.md` and `cli-native.md`, `alpha next` line, `commands.md` regenerated.

## Decisions
- R1 uses `workers/rdagent/idea_families.py` in a child process (standard library only), so no ALPHA package imports the worker.
  Closed families and dropped names come from `--closed` and `--dropped`.
- R3 is parse and schema only: a proposal needs JSON `name`, `description` and the declared direction, clock and reason; code must parse.
- R4 (prefix check) is named "not run" in every report. It needs `alpha_factor_data.check_prefix_invariance`, the factor runtime and a frozen panel.
- The month cap counts spend recorded in the bench store only. The gateway keeps its own month budget.

## NOT built (protected path `workers/**`)
1. `log_content = true|false` in the run config. The gateway already has `--log-content` (`model_gateway.py:127,805,1248`), but it writes only
   `ts`, instructions, prompt and reply to `content.jsonl`. It does not write stage, model, provider, tokens, cost or latency. The launcher
   `factor_loop_launch.py` has no `--log-content` option, so a config key would put an unknown flag on its command line. Needs a worker change.
2. The stage-label defect. Labels come from `label_calls` (`factor_loop_launch.py:84`). It picks the latest-starting step interval that holds a
   call's timestamp, across ALL loops. When two loops overlap, a call can take the other loop's step. This is my reading from the code only;
   I did not reproduce it, and I did not find the design note the brief names. No fix and no test were written.
   Fix idea for the worker owner: match the call to the loop that made it (carry the loop in the request), then add a test with two overlapping loops.

## Fail-first evidence
`uv run pytest tests/unit/test_rdagent_bench.py` first failed at collection: `No module named 'alpha_cli.rdagent_bench_model'`. It now passes (11 tests):
plan arithmetic, over-cap refusals, missing price and tokens, stage filter, resume, no ledger or memory change, store inside git refused,
paired scoring, refusal rules, null handling, plan writes nothing.
Not tested because the code is not mine to change: recording off by default, stage labels true.

## Commands for your machine (once the worker part exists)
(a) Record prompts on nightly runs: add `log_content = true` to `rdagent.toml`. This does NOT work yet; see item 1 above.
(b) Bench with real models, one gateway per model, prompts exported to `PROMPTS/*.json`:
1. `alpha rdagent bench plan --prompts PROMPTS --models m1,m2 --prices prices.toml --samples 2`
2. For each model, `export ALPHA_BENCH_TOKEN_<MODEL>=<that gateway's token>` (the model name in capitals, other characters as `_`)
3. `alpha rdagent bench run --prompts PROMPTS --models m1,m2 --prices prices.toml --samples 2 --store ~/alpha-bench --gateway m1=http://127.0.0.1:PORT1 --gateway m2=http://127.0.0.1:PORT2`
4. `alpha rdagent bench report --prompts PROMPTS --models m1,m2 --store ~/alpha-bench --closed "<family>"`

## Unverified
- The real gateway client was never run: its request and response shape (`provider`, `usage`) is assumed OpenAI-style.
- Provider pinning is the gateway's job; the bench only records what the call reports.
- No converter yet from the gateway's `content.jsonl` and `calls.jsonl` to the prompt files.
- The `verified:` stamp on the new tool card is a placeholder; `fs.py stale` will list it.

## Review round (Codex, 2026-11-21)
Five findings were correct and are fixed, each with a failing test first:
1. A stored output now carries a hash of its prompt; a changed prompt under the same id refuses the run.
2. A proposal's variables reach the family check, so composite proposals fall in their real families.
3. A resume checks the month cap against the calls still missing only.
4. A resume carries the run's spend forward, so the 10 USD run cap holds across reruns.
5. The proposal parser reads the worker's real format (an object keyed by factor name) as well as a single object.
The run code moved to `rdagent_bench_run.py` and the clients to `rdagent_bench_clients.py` to keep each module under 300 lines.

## Review round 2 (Codex)
Four more findings were correct and are fixed, each with a failing test first:
1. Feedback-stage outputs use the worker's feedback shape (Observations, Reasoning as text). A stage with no check is shown as "not checked", never as a failure.
2. The report reads every stored sample; the `--samples` option on `report` is gone.
3. A charge the gateway reports (`usage.cost`) is booked as the cost. A token-price estimate is labelled as an estimate.
4. A model name given twice is refused before any call.

## Review round 3 (Codex)
Two more findings were correct and are fixed, each with a failing test first:
1. Output folders are named with a reversible encoding of the model name (`a/b` and `a__b` no longer share one).
2. Stored samples are found by the exact prompt id plus a numeric suffix (`p` no longer reads the samples of `p.extra`).

## Review round 4 (Codex)
A call that fails after dispatch (for example a provider timeout) may still be billed. Its estimate is now charged to the month ledger and
kept in the store (`unsettled-spend.jsonl`), so a rerun counts it against the 10 USD run cap. A refusal before dispatch charges nothing.

## Review round 5 (Codex)
1. Each call now reserves its estimate in the shared month ledger under a file lock before it is sent, and settles to the reported or token-based
   charge after. A second bench process sees the reservation, so two runs cannot both take the last dollars. A refusal before dispatch releases it.
2. Failed dispatches are counted (in `unsettled-spend.jsonl`) against the 60-call cap on a rerun, as well as against the cost cap.

## Review round 6 (Codex)
Each gateway makes its own token, so one shared token failed on the second model. The client now reads `ALPHA_BENCH_TOKEN_<MODEL>` per model.
With a single gateway, `ALPHA_BENCH_GATEWAY_TOKEN` still works. Tokens are never stored.

## Review round 7 (Codex)
A coder reply is often a JSON envelope `{"code": "..."}`. The buildability check now parses the `code` string inside, not the envelope
(the envelope alone is a valid Python expression, so a broken program used to count as buildable).

## Review round 8 (Codex)
1. A store keeps one run budget: every output already in it counts toward the 10 USD and 60-call caps, whatever models, stages or prompts
   a later run selects.
2. One run at a time may use a store (a lock on `.run.lock`); a second is refused before any call. A billed reply is booked before it is saved.
