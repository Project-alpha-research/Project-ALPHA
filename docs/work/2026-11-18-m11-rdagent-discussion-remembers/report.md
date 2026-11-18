# Build report: m11-rdagent-discussion-remembers

## Changed files

Implemented all 11 items and left the changes uncommitted. The delivery gate and all 104 focused tests pass. The broader sandbox run had 72 failures or setup errors, all from the gateway’s existing storage guard.

† marks a file covered by the brief’s scope exception.

| Path | Change |
|---|---|
| `workers/rdagent/discussion.py` | Builds run-wide choice history, bounds quoted user data, records revision choices, and measures build and reply-to-proposal times. |
| `workers/rdagent/alpha_factor_judge.py` | Carries choices through hypothesis re-asks and feedback, refreshes closed types before revision, and records refusals and re-ask costs. |
| `workers/rdagent/research_memory.py` | Attaches the same choice block to experiment proposals after history filtering and budgeting. |
| `workers/rdagent/idea_families.py` † | Provides one task-family function for admission, proposals, and evaluated factors. |
| `workers/rdagent/factor_loop_launch.py` † | Passes the requested round count to the worker and reports final chat and embedding usage against their respective caps. |
| `apps/alpha-cli/src/alpha_cli/rdagent_discussion.py` | Prints results, refusal explanations, glossary meanings, agent choices, usage, and round-aware estimates. |
| `apps/alpha-cli/src/alpha_cli/_rdagent_ledger.py` | Validates `agent_choices` before writing a factor row. |
| `apps/alpha-cli/src/alpha_cli/rdagent_journey_words.py` † | Provides the discussion’s result sentences alongside the existing journey verdict wording. |
| `tests/unit/test_rdagent_discussion.py` | Tests prompt bytes, hostile notes, run history, revision instructions, refusal accounting, family identity, and timing. |
| `tests/unit/test_rdagent_discussion_commands.py` | Tests printed results and decisions, legacy records, glossary agreement, separate usage caps, and final-round estimates. |
| `workers/rdagent/README.md` | Documents what the agent remembers and what the user sees before and after a build. |
| `workers/rdagent/CONTEXT.md` | Updates worker routing for discussion history, re-asks, and build timing. |
| `docs/reference/project/components/rd-agent.md` | Updates the component description. The page is 191 lines. |
| `research/tools/rdagent-journey.md` | Points readers to prior-round results. The card is 40 lines. |
| `docs/reference/glossary.md` † | Adds one-line family meanings and the labels for unknown types. |
| `apps/alpha-cli/CONTEXT.md` † | Updates CLI routing for stored idea verdicts. |
| `docs/reference/invariants/workers.md` † | Clarifies how feedback treats a user drop. |
| `docs/reference/project/components/command-line.md` † | Documents reading a built idea’s verdict through the discussion commands. |
| `docs/reference/project/reserved-period.md` † | Refreshes the verification stamp after checking the judge changes against the reserved-period rule. |
| `docs/verified-reasons.txt` † | Records the reason for that verification. |

## Checks

| Command | Result | Exit code |
|---|---|---:|
| `uv run pytest -q tests/unit/test_rdagent_discussion.py tests/unit/test_rdagent_discussion_commands.py` | PASS · 104 passed | 0 |
| `uv run pytest -q tests/unit -k "rdagent or ledger or journey or glossary or code_size or filesystem or docs_links or command"` | UNVERIFIED · unrestricted selection includes prohibited checks | — |
| Same broad selection with three workers and sandbox exclusions | FAIL · 1,412 passed, 26 skipped, 27 failed, 45 setup errors | 1 |
| `uv run pytest -q tests/bias_guards` | PASS · 207 passed, 4 skipped | 0 |
| `uv run python scripts/fs.py stale` | PASS · 120 documents checked, zero stale | 0 |
| `uv run python scripts/gate.py check --base origin/main` | PASS · all six stages | 0 |
| `uv run ruff check` on all 10 changed Python files | PASS | 0 |
| `uv run ruff format --check` on the same files | PASS | 0 |
| `uv run mypy` on all eight changed source files | FAIL · 19 isolated-worker diagnostics | 1 |
| `uv run mypy` on the seven sources checkable in the root environment | PASS | 0 |
| `git diff --check` | PASS | 0 |

All 72 broad-suite failures or errors came from `test_rdagent_model_gateway.py` and `test_rdagent_budget_and_caps.py`. Their fixtures create state under `/tmp`, where the sandbox exposes `/tmp/.git`. The gateway rejects that location before the assertions can exercise the requested behavior.

**Verification by brief item**

| Item | Fix and proof |
|---:|---|
| 1 | Removed the consume-and-clear path. A fake refused its first proposal. Both the hypothesis and experiment prompts contained the complete, byte-equal block on the first ask and the re-ask. |
| 2 | Feedback receives the same delimited data and a fixed instruction to assess only built ideas. The hostile-note test checks the user prompt and system prompt separately. |
| 3 | Decisions supply drops, revision notes, and notes to the agent newest first. Tests verify whole-entry omission under 4,000 characters and remember when the user adds a dropped idea back. |
| 4 | The revision reads closed types immediately before its call. A test changes the ledger while the worker waits and verifies that the revision sees the new closure and glossary meaning. |
| 5 | The revision instruction assigns requested removals to `honoured`. CLI tests cover both renamed labels and missing explanations. |
| 6 | Evaluated factors carry their discussion round. Tests cover skipped rounds, pending and closed proposals, `--last-decision`, stricter-check failures, and an evaluation still being written. |
| 7 | **Cause:** proposal and ledger code already invoked the same underlying classifier. The CLI’s family-name lookup collapsed unmatched `other:` families and `composite: unknown inputs` to “not classified.” A test now compares the offered family with the actual ledger row, and another checks the display vocabulary against the glossary. |
| 8 | The existing revision call tells the agent to use only the user’s stated inputs and terms. Tests verify stored and printed `agent_choices`, the five-string and 200-character bounds, and a single charged call for revisions and additions together. |
| 9 | Replaced the last build-to-next-pause estimate with separate measurements. An injected clock verifies both intervals. CLI tests verify the final-round median and “several minutes” fallback. |
| 10 | The proposal stores refused names, reasons, and the run’s measured chat-call increase during re-asks. The fake records two chat calls and eight embeddings. The printed re-ask cost is two. |
| 11 | Usage comes from gateway counters. Tests verify that 31 chat calls and 253 embedding calls appear against their own caps in proposal and completion output. |

The hypothesis, experiment, re-ask, feedback, and revision prompt tests check the fixed data warning and JSON quoting. The revision test also verifies that replacing benign text with hostile text changes only its quoted value. The no-`--discuss` byte-proof test is identical to `HEAD` and passed, restoring the legacy round bytes after removing only the previously documented additive fields.

<details>
<summary>Exact proposal output after a refused first proposal, from the fake run</summary>

```text
RD-Agent proposes 1 idea for round 2.
You have until 17:12 UTC (1 minute). If you do not answer, the run builds every idea as proposed.
ALPHA refused the agent's first proposal for this round (the idea type is closed: price swings and market sensitivity). The agent asked again; this used 2 of the run's model calls.

1. Carry
   The agent gave no plain sentence.
   It expects coins with higher numbers to earn more over the next 7 days.
   Holding period: about 7 days.
   Coins ranked each period: 141.
   How often positions change: every 7 days.
   Idea type: futures funding.
   The agent's reason: Demand persists.
   Data it plans to read: not recorded.

Model budget left in this run: 4 chat calls, $10.00.
Usage in this run: 2 of 6 chat calls, 8 of 2000 embedding calls.
Idea types closed after repeated failed tries: price swings and market sensitivity.
A rule that is true on only a few days cannot rank coins. If your idea is an on/off condition, ask for a graded version (how strongly, not yes or no).

To answer, run:
  alpha ledger reply --run-dir run --as owner
Then add what you want to change. Name an idea by its number or its name:
  --drop 1                      do not build idea 1 (add =reason to say why)
  --revise "1=what to change"   ask the agent to change idea 1
  --idea "your idea"            add your own idea (two at most)
  --note "text"                 tell the agent something for this run
Ideas you do not name are built as proposed.
A stand-in user answers with --as stand-in instead of --as owner.
```

</details>

<details>
<summary>Exact last-decision output with a closed-type refusal</summary>

```text
Last decision, round 0:
Built: Carry.
You dropped Season. You gave no reason.
Not built: your idea "Try volatility." (the agent named it volatility_30d). Why: price swings and market sensitivity. How much prices vary or move with the market. This idea type is closed in this run after 3 failed tries (limit 3). You can ask for a different kind of signal.
Changed Funding into Carry, as you asked.
   What the agent changed: Used carry.
   What the agent did not do, and why: nothing.
Results are not ready.
```

</details>

**Exact result lines from the synthetic verdict fixture**

```text
Old: failed the quick test (the result could easily be luck).
Leak: used information from the future, so the result is void.
Pass: passed the quick test; it goes on to the stricter checks.
```

## UNVERIFIED

- No real RD-Agent loop or provider call ran. Whether a live model follows the user-idea wording remains unverified.
- The unrestricted broad selection needs an environment that permits sockets, servers, FastAPI `TestClient`, and browser checks. The smoke suite did not run.
- Standalone typing of `alpha_factor_judge.py` needs the isolated worker imports. All 19 diagnostics matched those reproduced on the unchanged `HEAD` source.

## Deviations

No model call or research-rule change was added. Two implementation readings affect edge cases. Legacy verdicts require an unambiguous link to a decision. When JSON escaping makes mandatory revision directions too long for one data block, the existing single call carries multiple bounded, one-line blocks so every request remains intact. Historical choices retain their single 4,000-character cap.

## Questions

None.

## Fix round 1

## Changed files

None in this verification round. The discussion changes remain uncommitted.

## Checks

| Command | PASS / FAIL / UNVERIFIED | Exit code |
|---|---|---:|
| `uv run python scripts/gate.py check --base origin/main` (external verifier) | FAIL | 1 |
| `uv run pytest -q tests/unit/test_rdagent_model_gateway.py tests/unit/test_rdagent_budget_and_caps.py --tb=short` | FAIL — 27 failed, 21 passed, 45 errors | 1 |
| `git diff --exit-code origin/main -- workers/rdagent/model_gateway.py tests/unit/test_rdagent_model_gateway.py tests/unit/test_rdagent_budget_and_caps.py` | PASS | 0 |
| `uv run pytest -q tests/unit/test_rdagent_discussion.py tests/unit/test_rdagent_discussion_commands.py` | PASS — 104 passed | 0 |

## UNVERIFIED

The external gate’s output tail omits the first traceback. Its failure and error counts match the local reproduction exactly, but the external host’s `/tmp/.git` status remains unverified.

## Deviations

None.

## Questions

Does the external verifier’s first traceback contain `ValueError: state is stored under the data directory, never in git`?

Locally, that guard accounts for all 72 failures and setup errors. Both fixtures create gateway state under `/tmp`, and `/tmp/.git` exists. The gateway and both test files match `origin/main`. The prior review explicitly reverted a fixture workaround for this same condition as outside the discussion change, so I left the files untouched. If the traceback matches, the gate needs a verifier where `/tmp` is outside Git. If it differs, the first traceback is needed to identify the external failure.

## Fix round 2

## Changed files

None in this verification round. The existing discussion changes remain uncommitted.

## Checks

| Command | PASS / FAIL / UNVERIFIED | Exit code |
|---|---|---:|
| `uv run python scripts/gate.py check --base origin/main` on the external verifier | FAIL — 27 failed, 45 errors | 1 |
| `python -m pytest -q tests/unit/test_rdagent_model_gateway.py --tb=short` against an isolated copy from `origin/main` | FAIL — 26 failed, 45 errors | 1 |
| `uv run pytest -q tests/unit/test_rdagent_budget_and_caps.py::test_gateway_counts_timeout_retry_only_after_reservation tests/unit/test_rdagent_model_gateway.py::test_messages_and_model_validation --tb=short` | FAIL — both reached the same storage guard | 1 |
| `git diff --exit-code origin/main -- workers/rdagent/model_gateway.py tests/unit/test_rdagent_model_gateway.py tests/unit/test_rdagent_budget_and_caps.py` | PASS | 0 |
| `uv run pytest -q tests/unit/test_rdagent_discussion.py tests/unit/test_rdagent_discussion_commands.py` | PASS — 104 passed | 0 |

## UNVERIFIED

The external gate log retains only the output tail. Its failure counts match the local reproduction, but its first exception and the external host’s `/tmp/.git` status remain unverified.

## Deviations

None.

## Questions

Can the verifier capture the first traceback with `uv run pytest -q -x tests/unit/test_rdagent_model_gateway.py --tb=short`?

The local failure is outside the discussion plan. Both fixtures hard-code `/tmp`. Here, `/tmp/.git` exists, so the gateway raises `ValueError: state is stored under the data directory, never in git` before the affected tests exercise their intended behavior. The isolated `origin/main` run reproduced all 45 setup errors and 26 failures. The unchanged budget test accounts for the 27th failure. The prior review explicitly reverted a fixture workaround for this condition. [Prior review decision](docs/work/2026-11-18-m11-rdagent-discussion-listens/report.md#review-round-claude)
