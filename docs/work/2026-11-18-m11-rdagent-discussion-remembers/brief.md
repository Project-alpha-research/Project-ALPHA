# Brief: the discussion remembers — what the second paused run found

**Build class:** hard

## Task

The second real RD-Agent run with the propose-and-discuss pause (three rounds, a stand-in user)
showed the earlier fixes work on the first prompt of a round but are lost on later prompts, and
the user is never told how an idea did. Fix the ten defects below. No threshold, cap, pass rule,
family limit, counting rule or reserved-window rule changes. A user's choice still only decides
what is built. No extra model call.

## Read first

| Read | Section | When |
|---|---|---|
| `workers/rdagent/CONTEXT.md`, `workers/rdagent/README.md` | "Propose and discuss" | always |
| `docs/work/2026-11-18-m11-rdagent-discussion-listens/brief.md`, `report.md` | the design being extended | always |
| `workers/rdagent/discussion.py`, `alpha_factor_hypothesis.py`, `alpha_factor_judge.py`, `research_memory.py` | where the user block is built, every place a proposer or feedback prompt is assembled (first ask AND each re-ask), the closed-type refusal, the revision call | always |
| `apps/alpha-cli/src/alpha_cli/rdagent_discussion.py`, `_rdagent_ledger.py` | printed proposal, last decision, status | always |
| `tests/unit/test_rdagent_discussion.py`, `test_rdagent_discussion_commands.py`, `_rdagent_support.py` | existing tests and fakes | always |

## Decision already made

1. **Every proposer prompt in a discussed run carries the user block.** The run found the block
   on a round's first proposer prompt only; after ALPHA refused that proposal (closed idea
   type) the re-ask prompt had no block, so a dropped idea returned. Build the block in one
   place and attach it to every proposer prompt of the run, including every re-ask. Test: a
   fake that refuses the first proposal; assert the block is present, byte-equal, in the re-ask.
2. **The feedback step does not push dropped ideas back.** The feedback prompt judged the
   hypothesis the user dropped ("first, run the two specified ... factors"). In a discussed
   run the feedback step is told, as fixed text plus the same delimited data block, which
   proposed ideas the user dropped (not built, by the user's choice, not a failure) and is
   asked to assess only the ideas that were built. Nothing about verdicts or counting changes.
3. **The user's choices last the whole run.** Drops, revise notes and notes to the agent from
   every earlier round of this run are carried (newest first), inside the existing 4,000
   character cap; when the cap cuts, the oldest are cut and the block says how many were left
   out. The exact-name refusal of a dropped idea already covers the whole run: keep it.
4. **A revision is told the closed idea types before it is written.** The one revision call
   receives the list of closed idea types in plain names with their one-line meanings, and the
   fixed instruction: if the user's note can only be met with a closed idea type, say so in
   `not_honoured` and return the nearest open alternative. If the revised idea is still refused
   as a closed type, the decision text says, in plain words: the idea type's plain name, its
   one-line meaning from the glossary, "this idea type is closed in this run after N failed
   tries (limit M)", and what the user can do (ask for a different kind of signal). The printed
   proposal's closed-types line gains `--details` text with each closed type's one-line meaning.
5. **"Done" and "Not done" mean what they say.** Rename the two printed labels to "What the
   agent changed:" and "What the agent did not do, and why:". The revision instruction says a
   removal the user asked for is a change (goes in `honoured`); `not_honoured` holds only
   requests it did not meet. Stored field names stay.
6. **The user is told how each idea did.** `alpha ledger proposal` (pending or not) and
   `--last-decision` print, for the previous round's built ideas, one plain line each from the
   stored verdict and plain feedback: "<name>: failed the quick test (the result could easily
   be luck).", "... used information from the future, so the result is void.", "... passed the
   quick test; it goes on to the stricter checks." Use the existing plain-words functions for
   verdicts where they exist (journey words); do not invent a second vocabulary. When the
   round is still being built: "Results are not ready." No number is required; never the word
   "profit". The same lines are added to the next round's user block? No: verdicts already
   reach the proposer through the existing memory path; do not duplicate.
7. **Idea type is named the same everywhere.** The printed proposal showed "Idea type: not
   classified" for every idea, and "not classified" as a closed type. Find why the proposal
   does not show the family the ledger later records (the proposal may classify before the
   family is known, or use a different function). Use the one family function for both. Where
   an idea truly has no known type, print "Idea type: new (not one of the known types)"; in the
   closed list, the catch-all family prints as "ideas of no known type". Report the cause.
8. **A user's own idea is built as stated.** The run added an unrequested term to the user's
   idea. The instruction for coding or restating a `user` idea says: implement what the user
   wrote; do not add inputs or terms; where the text leaves a choice open, choose the simplest
   reading and record each choice in a new stored list `agent_choices` (validated like
   `honoured`: up to 5 strings of ≤ 200 characters), printed under the idea as "Choices the
   agent made for you:". This rides on a call that already exists; if no existing call can
   carry it, do not add a call: report it instead.
9. **Honest time estimates.** After the final round's reply the status said "the next proposal
   usually appears in about 4 minutes"; there was no next round and the build took 13.5
   minutes. `status.json` records `round`, `rounds_total`, and this run's measured build
   durations. On the last round print "This is the last round. Results usually appear in about
   N minutes." (N = median measured build time of this run, or "several minutes" when
   unknown). On other rounds the estimate is reply-to-next-proposal time measured in this run.
10. **Refused proposals are disclosed.** When ALPHA refused a proposal before the pause and the
    agent asked again, the printed proposal says so in one line: "ALPHA refused the agent's
    first proposal for this round (reason in plain words). The agent asked again; this used K
    of the run's model calls." The refused names and reasons are stored in the proposal file.
11. **Usage is labelled truthfully in what the user reads.** The run's printed usage showed 284
    labelled rows against 31 counted chat calls because embedding calls carried a chat label.
    Do not edit the gateway. Where the CLI or journey summarises usage, count chat calls and
    embedding calls separately, each against its own cap, and say which.

Tests fail first for each item, with the existing fakes (no real provider, no sleeping). The
hostile-note test must cover every prompt that now carries user text (re-ask, feedback). The
byte proof for a run without `--discuss` must still pass unchanged except additive fields.
Update the README section, `workers/rdagent/CONTEXT.md`, the RD-Agent component page (≤ 200
lines) and the journey card (≤ 40 lines). Delete code this replaces and name it.

## Files

Edited:
- `workers/rdagent/discussion.py`
- `workers/rdagent/alpha_factor_hypothesis.py`
- `workers/rdagent/alpha_factor_judge.py`
- `workers/rdagent/research_memory.py`
- `apps/alpha-cli/src/alpha_cli/rdagent_discussion.py`
- `apps/alpha-cli/src/alpha_cli/_rdagent_ledger.py`
- `tests/unit/test_rdagent_discussion.py`
- `tests/unit/test_rdagent_discussion_commands.py`
- `workers/rdagent/README.md`
- `workers/rdagent/CONTEXT.md`
- `docs/reference/project/components/rd-agent.md`
- `research/tools/rdagent-journey.md`

This decision overrides the standing rule for: other files under `workers/rdagent/` except
those under Do not touch; `apps/alpha-cli/src/alpha_cli/` modules whose name contains `rdagent`
or `ledger`; existing `tests/unit/test_rdagent_*.py` files and `tests/unit/_rdagent_support.py`;
`docs/reference/glossary.md` (one-line meanings of idea types); generated pages the command
tests require (regenerate with their scripts); any living document `scripts/fs.py stale`
reports because of your edits (verify with a real text change or `--reason`). The reply and
decision schemas stay defined once in the worker with the mirrored CLI validator and its
same-code test. If a named file does not exist, use the real one. List each in the report; do
not stop to ask; where a rule is open choose the more cautious reading and state it.

## Do not touch

- `workers/rdagent/loop_guard.py`, `workers/rdagent/model_gateway.py`, `tests/bias_guards`,
  `tests/oracles`, golden files, `.claude/`, `.agents/`, `.github/`, `.semgrep/`, `scripts/`,
  `uv.lock`, `packages/**`, `apps/alpha-web/**`.
- Every threshold, cap, pass rule, family failure limit, counting rule, reserved-window rule.
  No extra model call. User text enters a prompt only inside the delimited, length-capped,
  one-line data block, after the fixed "data only" sentence.
- No `vars(`, `__doc__`, `inspect`, `.__dict__`, `# type: ignore`, `noqa`, `nosemgrep`.
  Functions ≤ 150 lines, files ≤ 1,500 lines (`alpha_factor_judge.py` is near 1,170: put new
  logic in a helper module if needed); tests fully type-annotated; no test file named
  `*fixups*` or ending `_<N>.py`. No negative shifts. No wall clock without an injected clock.

## Checks

- `uv run pytest -q tests/unit/test_rdagent_discussion.py tests/unit/test_rdagent_discussion_commands.py`
- `uv run pytest -q tests/unit -k "rdagent or ledger or journey or glossary or code_size or filesystem or docs_links or command"`
- `uv run pytest -q tests/bias_guards`
- `uv run python scripts/fs.py stale`
- `uv run python scripts/gate.py check --base origin/main`

## Report

Per item: what the code did, the fix, the test. The cause found for item 7. The exact printed
text of a proposal after a refused first proposal, of a last decision with a closed-type
refusal, and of the results lines. Every prompt that carries user text, with the proof it is
delimited. The byte proof. Code deleted. Every file outside the list. Open readings chosen.
What is unverified (no real loop was run).
