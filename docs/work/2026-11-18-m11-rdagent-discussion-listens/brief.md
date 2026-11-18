# Brief: the discussion listens — what a stand-in trader found in the first real paused run

**Build class:** hard

## Task

The first real RD-Agent run with the propose-and-discuss pause (two rounds, a stand-in user)
worked mechanically: the loop paused, drops left no ledger row, a revision cost one counted
call, a user idea was built and labelled. But the user did not feel heard, and the proposal
was hard to judge. Fix the twelve defects below. No threshold, cap, pass rule, family limit,
counting rule or reserved-window rule changes. A user's choice still only decides what is built.

## Read first

| Read | Section | When |
|---|---|---|
| `workers/rdagent/CONTEXT.md`, `workers/rdagent/README.md` | "Propose and discuss" | always |
| `docs/work/2026-11-18-m11-rdagent-propose-and-discuss/brief.md`, `report.md` | the design being corrected | always |
| `workers/rdagent/discussion.py`, `alpha_factor_hypothesis.py`, `alpha_factor_judge.py`, `research_memory.py` | proposal file, reply effects, the revision call, what the next round's proposer is told | always |
| `apps/alpha-cli/src/alpha_cli/rdagent_discussion.py`, `ledger_cmds.py` | `alpha ledger proposal`, `alpha ledger reply` | always |
| `apps/alpha-cli/src/alpha_cli/rdagent_journey.py`, `rdagent_journey_words.py` | step 1 text and the "who" tag | item 10 |
| `tests/unit/test_rdagent_discussion.py`, `test_rdagent_discussion_commands.py` | existing tests and fakes | always |
| `docs/reference/glossary.md` | plain names for idea families | item 8 |

## Decision already made

1. **Record `plain_summary_status`** (`ok`, `missing` or `rejected`) beside `plain_summary` in
   the round record, the proposal file and each new ledger row (additive).
2. **Two labels, two meanings.** `origin` says who wrote the idea (`agent`,
   `agent-revised-by-user`, `user`). Rename what is stored as `author` on built ideas to
   `answered_by` (who answered the proposal), additive: keep writing `author` with the same
   value for readers that already use it, and say in the README that `author` is deprecated.
3. **A revision must answer the note.** The revision call asks the model to return, per revised
   idea, `honoured` (a list of short plain statements of what it changed because of the note)
   and `not_honoured` (what it did not do, each with a reason). Both are validated (lists of
   strings, each ≤ 200 characters), stored in `decision.json` and the round record, and shown
   by `alpha ledger proposal --last-decision` (item 11). A revised idea must not re-introduce an
   idea the same reply dropped: compare the revised idea's name and family with the dropped
   ideas'; on a match (same name, or same family and the note did not ask for that family),
   drop the revised idea with the reason "revision returned a dropped idea" — no extra call.
4. **The next round is told what the user said.** The next round's proposer context gets one
   delimited, length-capped data block: each dropped idea's name, family and the user's reason;
   each revise note; the note to the agent. The instruction sentence (fixed text, not user
   text) says: do not propose again an idea the user dropped in this run, or a close variant of
   it, unless the user asks. Enforce it after the proposal: an idea whose name equals a dropped
   idea's name in this run is refused before the pause with the reason "you dropped this idea
   in round N" and shown in the proposal as refused, not offered again. This refusal is not a
   failed try and adds no ledger row.
5. **Warn before building an idea that will rarely fire.** This needs no model call and no
   reserved data: after coding and execution, the evaluator already detects a degenerate factor
   (most days tied). Nothing changes there. But in the proposal step, for a `user` idea or a
   revised idea, the proposal file and printed text carry the fixed caution: "A rule that is
   true on only a few days cannot rank coins. If your idea is an on/off condition, ask for a
   graded version (how strongly, not yes or no)." And the revision instruction asks the model
   to express an on/off user condition as a graded number where it can, stating that in
   `honoured`. After judging, a degenerate verdict's plain feedback says what share of days
   were tied.
6. **The reply confirmation echoes everything**: each drop with its reason, each revise note,
   each user idea's text, the note to the agent.
7. **Answer by number.** `--accept`, `--drop` and `--revise` take the list number shown in the
   proposal (1, 2, …) as well as the name; the confirmation prints the resolved names. A number
   out of range is refused with the list.
8. **The proposal reads like a trader's summary.** Per idea, in this order, each a short plain
   sentence: the plain sentence (or "The agent gave no plain sentence."); what it expects;
   "Holding period: about N days" (from the declared horizon); "Coins ranked each period: N"
   (from the panel's instrument count when recorded); "How often positions change: every N
   days" (from the declared clock) when recorded; idea type in plain words from the glossary
   (an unknown family prints "idea type: not classified", never an internal key such as
   `other: first`); the agent's reason with internal field names and markup stripped (no
   `proposal_metadata`, no JSON keys, no braces); data it plans to read in plain names
   (`funding_rate` → "funding rate"). Missing facts print "not recorded".
9. **Family lists move out of the way.** The printed proposal shows one line: "Idea types
   closed after repeated failed tries: A, B." (plain names, at most five, then "and N more").
   The full open/closed text stays in `proposal.json` and prints only with `--details`.
10. **Journey step 1 names the right author.** The tag is "You (the user)" for `origin: user`,
    "RD-Agent (AI), changed at your request" for `agent-revised-by-user`, and "RD-Agent (AI)"
    otherwise; when the answer came from the stand-in, the tag adds "— answered by a stand-in
    user". The plain sentence is shown whole (no clause dropped): cap by whole sentence, not by
    cutting a condition.
11. **You can see what happened to your answer.** `alpha ledger proposal --run-dir <dir>` with
    no pending proposal prints the state in one or two plain sentences: "No proposal is
    waiting. Round N is being built: X ideas. The next proposal usually appears in about M
    minutes." (M from this run's earlier round, or "a few minutes" when unknown) and the last
    decision: what was built, dropped, changed, with `honoured` / `not_honoured`.
    `--last-decision` prints only that. The worker writes a small `discussion/status.json`
    (state, round, since) at each transition so the command reads state, never guesses.
12. **The wait is stated first.** The first two lines of the printed proposal are: how many
    ideas, and "You have until HH:MM UTC (N minutes). If you do not answer, the run <stops and
    builds nothing | builds every idea as proposed>."

Tests fail first for each item, with the existing fakes (no real provider, no sleeping). The
hostile-note test and the byte proof for a run without `--discuss` must still pass unchanged
except for additive fields (show that removing them restores the old bytes). Update the README
section, `workers/rdagent/CONTEXT.md`, the RD-Agent component page (≤ 200 lines), the journey
card (≤ 40 lines). Delete code this replaces (for example the old families text builder for the
printed proposal if unused) and name it in the report.

## Files

Edited:
- `workers/rdagent/discussion.py`
- `workers/rdagent/alpha_factor_hypothesis.py`
- `workers/rdagent/alpha_factor_judge.py`
- `workers/rdagent/research_memory.py`
- `apps/alpha-cli/src/alpha_cli/rdagent_discussion.py`
- `apps/alpha-cli/src/alpha_cli/ledger_cmds.py`
- `apps/alpha-cli/src/alpha_cli/_rdagent_ledger.py`
- `apps/alpha-cli/src/alpha_cli/rdagent_journey.py`
- `apps/alpha-cli/src/alpha_cli/rdagent_journey_words.py`
- `tests/unit/test_rdagent_discussion.py`
- `tests/unit/test_rdagent_discussion_commands.py`
- `workers/rdagent/README.md`
- `workers/rdagent/CONTEXT.md`
- `docs/reference/project/components/rd-agent.md`
- `research/tools/rdagent-journey.md`

This decision overrides the standing rule for: other files under `workers/rdagent/` except
those under Do not touch; `apps/alpha-cli/src/alpha_cli/` modules whose name contains `rdagent`
or `ledger`; existing `tests/unit/test_rdagent_*.py` files and `tests/unit/_rdagent_support.py`;
`docs/reference/glossary.md` (plain names for idea families); generated pages the command tests
require (regenerate with their scripts); any living document `scripts/fs.py stale` reports
because of your edits (verify with a real text change or `--reason`). The reply and decision
schemas stay defined once in the worker with the mirrored CLI validator and its same-code test.
If a named file does not exist, use the real one. List each in the report; do not stop to ask;
where a rule is open choose the more cautious reading and state it.

## Do not touch

- `workers/rdagent/loop_guard.py`, `workers/rdagent/model_gateway.py`, `tests/bias_guards`,
  `tests/oracles`, golden files, `.claude/`, `.agents/`, `.github/`, `.semgrep/`, `scripts/`,
  `uv.lock`, `packages/**`, `apps/alpha-web/**`.
- Every threshold, cap, pass rule, family failure limit, counting rule, reserved-window rule.
  No extra model call beyond the one existing revision call per round.
- No `vars(`, `__doc__`, `inspect`, `.__dict__`, `# type: ignore`, `noqa`, `nosemgrep`.
  Functions ≤ 150 lines, files ≤ 1,500 lines; tests fully type-annotated; no test file named
  `*fixups*` or ending `_<N>.py`. No negative shifts. No wall clock without an injected clock.

## Checks

- `uv run pytest -q tests/unit/test_rdagent_discussion.py tests/unit/test_rdagent_discussion_commands.py`
- `uv run pytest -q tests/unit -k "rdagent or ledger or journey or glossary or code_size or filesystem or docs_links or command"`
- `uv run pytest -q tests/bias_guards`
- `uv run python scripts/fs.py stale`
- `uv run python scripts/gate.py check --base origin/main`

## Report

Per item: what the code did, the fix, the test. The exact printed text of `alpha ledger
proposal` for a two-idea example (one with every fact, one with facts missing), of the reply
confirmation, and of the no-pending state. The byte proof. Code deleted. Every file outside the
list. Open readings chosen. What is unverified (no real loop was run).
