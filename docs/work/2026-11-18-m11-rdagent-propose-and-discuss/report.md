# Build report: m11-rdagent-propose-and-discuss

The optional pause works in tests and in a two-process trial with the real commands. No real
RD-Agent loop was run and no model budget was spent. A supervised run comes next.

## What it does

`--discuss` adds one pause per round. After the proposal passes the family and declaration
checks, and before any coding call, the worker writes the proposal and waits for an answer.
Without `--discuss` the loop runs as before; only the `plain_summary` fields are new.

## Round flow with the pause

1. RD-Agent proposes. The family and declaration refusals run exactly as before.
2. The worker writes `discussion/round-<n>/proposal.json`: run id, round, time, deadline, the
   timeout policy, calls and dollars left under the caps, the open and closed families, and per
   idea its name, plain sentence (or its status), family, direction, holding period, the agent's
   reason (600 characters at most) and the columns it plans to read.
3. The worker checks for `reply.json` once a second, under a folder lock. It makes no model
   call while it waits. An invalid file becomes `reply.invalid-<k>.json`, the error goes to
   `reply.error.txt`, and the wait continues.
4. `alpha ledger proposal` prints the ideas. `alpha ledger reply` writes `reply.json` atomically,
   under the same lock. Ideas not named are accepted.
5. The worker applies the answer, writes `decision.json` and appends a `discussion` row to
   `rounds.jsonl` (`trial_created: false`). Only the selected ideas reach the coder and judge.
6. Each built idea carries `origin` and `author` into the round record and its ledger row.

## Reply choices

| Choice | Effect | Recorded | Test |
|---|---|---|---|
| accept | Built as proposed, origin `agent` | decision, round record, ledger row | `test_wait_invalid_then_accept_drop` |
| drop | Never built: no ledger row, no family failure, no look | decision `dropped` with reason | `test_trial_ledger_only_receives_selected_tasks`, `test_all_dropped_never_enters_coder` |
| revise | One extra proposal call covers all revisions and user ideas; replacements pass the same refusals | origin `agent-revised-by-user` | `test_single_revision_with_user_idea` |
| user idea | Same call and same refusals; no easier path | origin `user` | `test_revision_gateway_charge_and_guard` |
| note | Added once to the next round's proposal context, as quoted data | decision | `test_single_revision_with_user_idea` |

The gateway counts the extra call toward the existing caps (`counted_calls == 1` in the test).
If no call is left, or the gateway refuses with `budget_exhausted`, the revised ideas are dropped
with "call cap reached" and the accepted ones are built. The receipt labels the call
`discussion_revision`.

## Timeout

`proceed` (default) builds the proposal as written and records `reply: none (timed out)` with no
author. `stop` writes `loop-stop.json` with `loop_reason: awaiting-discussion` and ends the run
cleanly. Resume restores completed rounds only, so `stop` is a clean stop, not a resumable pause.
The launch's `--wall-seconds` limit still covers the waiting time.

## Byte proof without `--discuss`

`test_off_restores_round_bytes` removes the two summary fragments from the round record and
matches the old bytes exactly. `test_known_only_evaluation_bytes_match_declared_primary_baseline`
pops the two summary fields from a ledger row and matches the pinned digest.

## Review fixes (after the build)

- User text is capped at 500 characters per note, reason or idea (both validators).
- User text reaches the model as JSON strings after a fixed "data only" sentence, in both the
  revision call and the next round's note. `test_hostile_note_changes_only_the_idea_text` shows
  a hostile note changes only the note's own bytes in the prompt and the decision.
- An unusable revision answer (wrong shape, or the model returned no JSON) now drops only the
  revised ideas with the reason. Before, it stopped the whole run. Provider failures still go to
  the existing provider guard.
- A second reply, or a reply after the round closed or the run ended, is refused and kept as
  `refused-reply-<k>.json`.
- The two validator copies (worker and command line) are checked to be the same code, not only
  the same answers on fixtures (`test_validators_are_the_same_code`).
- Printed text of both commands rewritten: answer first, numbered ideas, short lines. Errors
  print a plain sentence instead of "Invalid value".
- Journey step one leads with the plain sentence and keeps the idea type and expected direction.
- The RD-Agent project page keeps the parts of the 2026-11-18 plan that are not built.
- Checked once with the real clock: a 3-second wait timed out after 3.0 s; a reply written after
  1.2 s was read at 2.0 s.

## Files outside the brief's list

`workers/rdagent/alpha_factor_judge.py` (the family guard and evaluator hand-off live there),
`tests/unit/test_rdagent_factor_eval.py`, `apps/alpha-cli/CONTEXT.md`,
`docs/reference/commands.md` (regenerated), `docs/reference/invariants/cli-trial-ledger.md`,
`docs/reference/invariants/workers.md`, `docs/reference/project/components/command-line.md`.

## Open readings chosen

- Timeout `stop` is a clean stop, because resume does not restore a half-started round.
- An unusable revision answer drops the revised ideas instead of stopping the run.
- The proposer is asked for `input_columns` only when `--discuss` is on.

## Unverified

- No real loop, provider or gateway server ran. The revision call's HTTP path was exercised
  against the in-process gateway, not the served one.
- How a real model fills `plain_summary` and `input_columns` is unknown until the supervised run.

Nothing is replaced by this change, so nothing is deleted.
