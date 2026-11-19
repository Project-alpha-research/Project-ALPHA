---
owner: rd-agent worker
sources:
  - workers/rdagent/discussion.py
  - apps/alpha-cli/src/alpha_cli/rdagent_discussion.py
verified: d96336e4199154fa
---

# RD-Agent worker: propose and discuss

The whole "Propose and discuss" section of the [worker page](README.md), moved here unchanged below the summary.

Summary of this page.

- Reply options: `alpha ledger reply` takes `--drop`, `--revise`, up to two `--idea` and one `--note`. Ideas you leave out are built as proposed.
- A note is one-way: it guides the agent's next proposal; the agent does not answer questions.
- Results lines: the proposal and `--last-decision` give one result per selected idea when its evaluation is ready.
- A stand-in user (`--as stand-in`, recorded as `stand-in user, not the owner`) only discusses ideas. Only the owner approves reserved-data slots, promotion, paper or live trading, and guard changes.
- The agent's reflection (hypothesis, observations, evaluation, new hypothesis and reason) is always passed on in full, also after a drop.

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
Remove `author` when no reader uses it.

A note guides the agent's next proposal. The agent does not answer questions.
The run saves a last-round note with the reply and tells you it will go unused.

A stand-in user only discusses ideas. Only the owner approves: reserved-data slots, promotion, paper or live trading, and guard changes
([rule](../../docs/reference/project/owner-decisions-5.md#2026-11-18-stand-in-user-while-ideas-are-throwaway-tests)). Owner approvals go only through
`apps/alpha-cli/src/alpha_cli/owner_auth.py`, and the `pre-owner-action-guard` hook in `scripts/claude_hooks.py` blocks agent tools
from the owner-action routes.

- The proposal starts with the deadline and timeout action, then a trader-style summary per idea and a caution about
  on/off rules. It names refusals before the pause and the chat calls spent asking again. Chat and embedding calls each
  have their own usage count and cap. The completed-run view also splits requests during coding by chat and embedding
  when the labelled rows are available. Use `--details` for the meaning of each closed idea type.
- The proposal and `--last-decision` give one result per selected idea when the evaluation is ready. Between proposals
  the command reads `discussion/status.json`. The next-proposal estimate uses the median time from a reply to the next
  proposal in this run. The final-round estimate uses the median from a reply to results. Before a measurement is available,
  the estimates say “a few minutes” for proposals and “several minutes” for results.
- Every proposer, including the experiment writer and both steps of a re-ask, sees this run’s drop reasons, revision notes
  and notes to the agent. The fixed data warning precedes one JSON line, newest first, with a 4,000-character cap and a
  count of older choices left out. Feedback sees only the names you dropped, in the same kind of block, with a fixed
  instruction to assess built ideas and avoid variants of drops. The agent's reflection (its hypothesis, observations,
  evaluation, new hypothesis and reason) is always passed on in full, also after a drop
  ([owner](../../docs/reference/project/owner-decisions-6.md#2026-11-19-never-reduce-rd-agents-capability-to-save-tokens-or-cost)).
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
  the type, its failed tries and the limit. Proposals warn when a failure would close an idea type. For added ideas,
  the warning appears in the decision after the agent restates the idea. Replacements meet the same checks as any idea.
- For your own idea the agent must use only the inputs and terms you gave. It records its simplest readings of open
  choices in `agent_choices`, with the same limits as revision statements. The decision prints each statement on its own line
  and lists agent choices for revisions too. It warns when the agent says a revised or added idea still uses an on/off condition.
- Notes, reasons and ideas are at most 500 characters each and reach the agent as quoted data.
  They cannot change a test, threshold or limit. A reply only chooses what is built; it never
  approves, admits or promotes anything.
- The default wait is 30 minutes, then the ideas are built as proposed. `--discuss-wait-minutes N`
  changes the wait; `--discuss-on-timeout stop` stops cleanly before coding instead. The launch's
  `--wall-seconds` limit still applies, so set it longer than the waits you expect.

Every proposed sentence carries `plain_summary_status` (`ok`, `missing` or `rejected`).
With the pause off, only the additive summary fields enter the round and trial records.
