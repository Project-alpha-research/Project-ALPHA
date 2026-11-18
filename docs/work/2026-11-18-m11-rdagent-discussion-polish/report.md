# Build report: m11-rdagent-discussion-polish

## Changed files

All nine fixes are implemented and left uncommitted. The delivery gate passed on the final tree. † marks a file covered by the brief’s scope exceptions.

- [apps/alpha-cli/src/alpha_cli/rdagent_discussion.py](apps/alpha-cli/src/alpha_cli/rdagent_discussion.py) — Updated proposal, reply, decision, timing and usage output.
- [apps/alpha-cli/src/alpha_cli/rdagent_journey_words.py](apps/alpha-cli/src/alpha_cli/rdagent_journey_words.py) — Explained degenerate verdicts with stored screening figures.
- [workers/rdagent/discussion.py](workers/rdagent/discussion.py) — Updated prompt data, revision validation, final-round notes and transition timing.
- [workers/rdagent/alpha_factor_judge.py](workers/rdagent/alpha_factor_judge.py) — Reused closure counts for last-try warnings and applied the discussion view to proposer and feedback prompts.
- [workers/rdagent/alpha_factor_hypothesis.py](workers/rdagent/alpha_factor_hypothesis.py) — Created prompt-only copies of affected hypotheses and trace entries.
- [tests/unit/test_rdagent_discussion.py](tests/unit/test_rdagent_discussion.py) — Added worker and prompt regression tests with fakes and an injected clock.
- [tests/unit/test_rdagent_discussion_commands.py](tests/unit/test_rdagent_discussion_commands.py) — Added exact CLI output, validator, timing and usage tests.
- [workers/rdagent/README.md](workers/rdagent/README.md) — Updated discussion behavior and documented removal of `author` when no reader uses it.
- [apps/alpha-cli/src/alpha_cli/ledger_cmds.py](apps/alpha-cli/src/alpha_cli/ledger_cmds.py) † — Updated `reply --help`.
- [workers/rdagent/research_memory.py](workers/rdagent/research_memory.py) † — Applied the discussion view to experiment-writer history.
- [workers/rdagent/CONTEXT.md](workers/rdagent/CONTEXT.md) † — Updated prompt and timing descriptions. 78 lines.
- [docs/reference/project/components/rd-agent.md](docs/reference/project/components/rd-agent.md) † — Corrected the feedback description. 191 lines.
- [research/tools/rdagent-journey.md](research/tools/rdagent-journey.md) † — Documented the stored figures used to explain rank failures.
- [apps/alpha-cli/CONTEXT.md](apps/alpha-cli/CONTEXT.md) † — Refreshed the verification stamp.
- [docs/reference/invariants/cli-trial-ledger.md](docs/reference/invariants/cli-trial-ledger.md) † — Refreshed the verification stamp.
- [docs/reference/invariants/workers.md](docs/reference/invariants/workers.md) † — Refreshed the verification stamp.
- [docs/reference/project/reserved-period.md](docs/reference/project/reserved-period.md) † — Refreshed the verification stamp.
- [docs/verified-reasons.txt](docs/verified-reasons.txt) † — Recorded why those four documents still apply.

| Item | Prior behavior | Fix and regression test |
|---|---|---|
| 1. Degenerate verdict | Appended an all-tied-day percentage even when it was zero. | Uses stored coverage, ties and screening reasons. The 54% ties and 42% coverage fixture checks the discussion line and journey verdict. |
| 2. Notes | Help described when the agent reads a note. | Help and confirmation say notes guide the next proposal. Tests check that a final-round note is saved, labelled unused and omitted from later prompts. |
| 3. Drops | The original round hypothesis and free-form feedback could carry dropped ideas forward. | Prompt tests cover feedback, hypothesis generation, experiment generation and the revision request. They verify that dropped text stays out and the saved trace retains its original text. |
| 4. Last try | The proposal listed already closed idea types. | Warns when one more failed try would close a type. A duplicate-ledger-row fixture verifies the distinct count and the warning for a user idea after restatement. |
| 5. On/off conditions | Revisions carried no flag for retained gates. | The existing revision call returns `uses_gate`. Tests cover true, false, missing and malformed values, plus the printed caution. |
| 6. Revised choices | The decision printed `agent_choices` for user ideas. | The revised-idea fixture verifies that its choices also print under the idea. |
| 7. Statement lists | Semicolon joins could produce `.;`. | Tests pin one bullet per statement and one final full stop. The existing revision prompt requests plain words without variable names. |
| 8. Timing | The final estimate used build duration. | An injected clock verifies reply-to-proposal and reply-to-results intervals. CLI tests verify separate medians and both fallback phrases. |
| 9. Usage | `coding` was a step label shared by chat and embedding rows. | The completed-run CLI splits labelled rows by endpoint and still uses charged attempts for the budget line. The mixed-row fixture checks 16 chat requests and 266 embedding requests. |

For item 3, the hypothesis proposer and experiment writer, including re-asks, render the built tasks’ names and descriptions in both history fields for affected rounds. Feedback receives the current built tasks’ names and descriptions and the instruction to avoid variants of drops. The revision request receives the current retained and explicitly revised task descriptions. Drop names stay in the bounded data blocks, alongside the existing choice metadata where applicable. Original hypothesis text and model feedback stay in the saved trace and round records. The hostile-note test and the non-discussed byte proof both passed.

The `coding` step comes from `record_steps`. The launcher’s `label_calls` matches requests to those step intervals, and `write_call_labels` saves the resulting `step` field in `calls-labelled.jsonl`. [factor_loop_entry.py](workers/rdagent/factor_loop_entry.py:51) · [factor_loop_launch.py](workers/rdagent/factor_loop_launch.py:85)

Removed the journey’s unconditional tied-day append, inline semicolon joins for explanations, build-only timing collection and lookup, and the revision prompt’s separate line of dropped names.

**Exact degenerate result line**

```text
Carry: about 54% of the values were tied and only 42% of coin-days had a value, so the coins could not be ranked.
```

**Exact revised decision**

```text
Last decision, round 0:
Built: Carry.
Changed Funding into Carry, as you asked.
   What the agent changed:
   - Kept cheaper coins.
   - Used the monthly payment.
   What the agent did not do, and why:
   - Costs were unavailable.
   Choices the agent made for you:
   - Used Monday.
   - Kept the old price condition.
   This idea still uses an on/off condition. It may have a value on too few days to rank coins.
   This idea type has failed 2 of 3 tries. If this idea fails, the type is closed for later rounds.
Results are not ready.
```

**Exact final-round reply confirmation**

```text
Your answer for round 2 is saved. RD-Agent reads it within seconds.
Answered by: the owner.
Build as proposed: Funding, Volume.
Note to the agent: Look at funding next.
A note guides the agent's next proposal. The agent does not answer questions.
This is the last round, so the note will not be used.
Saved in discussion/round-2/reply.json.
```

## Checks

| Command | PASS / FAIL / UNVERIFIED | Exit code |
|---|---|---:|
| `uv run pytest -q tests/unit/test_rdagent_discussion.py tests/unit/test_rdagent_discussion_commands.py` | PASS | 0 |
| `uv run pytest -q tests/unit -k "rdagent or ledger or journey or code_size or filesystem or docs_links or command"` | UNVERIFIED | — |
| Broad unit selection with sandbox exclusions, initial run | UNVERIFIED | 130 |
| Broad unit selection with sandbox exclusions, time-limited retry | FAIL | 1 |
| `uv run pytest -q tests/unit/test_rdagent_journey.py tests/unit/test_rdagent_journey_figures.py` | PASS | 0 |
| `uv run pytest -q tests/bias_guards` | PASS | 0 |
| `uv run python scripts/fs.py stale` | PASS | 0 |
| `uv run python scripts/gate.py check --base origin/main` | PASS | 0 |
| `uv run ruff check <changed Python files>` | PASS | 0 |
| `uv run ruff format --check <changed Python files>` | PASS | 0 |
| `uv run mypy <all changed source files>` | FAIL | 1 |
| `uv run mypy <six changed sources checkable in the root environment>` | PASS | 0 |
| `uv run python scripts/commands_reference.py --check` | PASS | 0 |
| `git diff --check` | PASS | 0 |

The focused suite passed 120 tests, the journey suite passed 22, and the bias guards passed 207 with four skipped. The gate passed all six stages, and the document check found zero stale files.

The broad retry recorded 1,429 passed, 29 skipped, 30 failed and 45 setup errors. The existing `/tmp/.git` storage guard accounted for 29 failures and all 45 setup errors, including two gateway launcher failures that stopped before socket setup. The other failure was a native fixture whose control socket bind the sandbox denied. Standalone mypy reproduced the same 19 isolated-worker diagnostics on the unchanged judge at `HEAD`. [Broad retry log](/tmp/alpha-m11-broad-retry.log) · [Mypy log](/tmp/alpha-m11-mypy-complete.log)

## UNVERIFIED

- The unrestricted broad selection, live socket and server checks, FastAPI `TestClient`, browser and smoke checks require an environment outside this sandbox.
- The first sandbox broad run stopped making progress near completion. The retry excluded the two in-process web API cases reached by the stalled workers.
- No real RD-Agent loop or provider call ran. The pinned upstream runtime and live model behavior remain unverified.

## Deviations

None from the decided behavior. The final-round estimate uses earlier reply-to-results measurements from the same run when available. A revised idea’s warning uses the type of the revision the worker accepted. The prompt view leaves out free-form feedback for affected historical rounds because older feedback can quote dropped text. A dropped name that cannot fit the existing prompt cap uses the existing unusable-revision path.

## Questions

None.
