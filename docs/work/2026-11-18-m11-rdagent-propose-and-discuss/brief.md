# Brief: RD-Agent proposes, the user answers, then it builds

**Build class:** hard

## Task

The owner's direction (decision log vol. 5, 2026-11-18): the agent is a collaborator, never a
black box. It proposes ideas; the user reads them, accepts, drops, redirects or adds an idea of
their own; then the agent builds and ALPHA judges. Today the loop runs proposal → code → judge
with no pause. Add an optional pause after each round's proposal, a plain sentence per idea, and
a record of who decided what. With the pause off, behaviour is exactly as today.

## Read first

| Read | Section | When |
|---|---|---|
| `workers/rdagent/CONTEXT.md`, `workers/rdagent/README.md` | whole | always |
| `docs/reference/project/owner-decisions-5.md` | stand-in user; collaborator not black box; RD-Agent chooses tests | always |
| `workers/rdagent/factor_loop_launch.py`, `factor_loop_entry.py` | launch options, round loop, caps, receipts | always |
| `workers/rdagent/alpha_factor_hypothesis.py` (the proposer wrapper), `idea_families.py`, `research_memory.py` | what a proposal contains; how a round's ideas reach the coder; refusals before coding | always |
| `workers/rdagent/model_gateway.py`, `loop_guard.py` | call and money caps (read only; no change) | always |
| `apps/alpha-cli/src/alpha_cli/ledger_cmds.py`, `rdagent_journey.py`, `rdagent_journey_words.py` | where run-folder commands live; journey step 1 text | commands |
| `tests/unit/test_rdagent_*.py`, `tests/unit/_rdagent_support.py` | fakes for the provider and the loop | tests |

## Decision already made

1. **Plain sentence per idea.** The proposer's instructions ask, for every idea, for
   `plain_summary`: one sentence of at most 30 words that says what the number measures and
   what it expects, with no formula symbols, variable names or code. The loop validates it
   (non-empty, ≤ 30 words, none of `( ) = _ { } \\ / * ^` and no `$`): a missing or invalid
   sentence is recorded as `plain_summary_status: missing | rejected` with the raw text kept,
   costs no extra model call, and never blocks the round. It is stored in the round record and
   on each new ledger row (additive field). The journey's step 1 shows it as its first sentence
   when stored and valid; otherwise today's wording.
2. **The pause.** New launch option `--discuss` with `--discuss-wait-minutes N` (default 30)
   and `--discuss-on-timeout proceed|stop` (default `proceed`). When on, after a round's
   proposal passes the existing pre-coding refusals and before any coding call, the loop writes
   `discussion/round-<n>/proposal.json` in the run folder and waits for
   `discussion/round-<n>/reply.json`.
   - `proposal.json`: run id, round, written-at, and per idea: name, `plain_summary` (or its
     status), idea family, expected direction and horizon, the agent's reason (its own words,
     capped at 600 characters), the input columns it plans to read, and how many calls and
     dollars remain under the caps. Plus the open and closed idea families in plain words.
   - `reply.json` (schema-validated; an invalid file is renamed `reply.invalid-<k>.json`, the
     error is written to `reply.error.txt`, and the wait continues): `author` — exactly
     `owner` or `stand-in user, not the owner`; per idea one of `accept`, `drop` (with an
     optional reason), `revise` (with a required note); optional `user_ideas`: a list of at
     most two plain-text ideas; optional `note_to_agent`.
   - Effects: `accept` → built as proposed. `drop` → not built; recorded; it is NOT a failed
     try and does not count toward a family's failure limit or the ledger's look count (nothing
     was tested). `revise` → the note goes to the proposer in ONE extra proposal call for the
     round covering all revised ideas and all `user_ideas` together; the returned ideas replace
     the revised ones and add the user's; they pass the same pre-coding refusals and are built
     without a second pause. That extra call counts toward the existing caps; if the cap would
     be exceeded, revised ideas are dropped with the reason "call cap reached" and the round
     continues with accepted ideas. `note_to_agent` is added to the next round's proposal
     context once.
   - Each built idea records `origin` (`agent`, `agent-revised-by-user` or `user`) and the
     `author` of the reply, in the round record and on its ledger row (additive fields).
   - Timeout: `proceed` builds the proposal as written and records `reply: none (timed out)`;
     `stop` ends the run cleanly with `loop_reason: awaiting-discussion` and a resumable state
     if resume already exists for the loop, else a clean stop. Waiting uses no model calls and
     an injected clock/sleep so tests do not sleep.
   - With `--discuss` absent nothing new is written except the `plain_summary` fields.
3. **Commands** (in the existing `ledger` group, beside `journey`):
   - `alpha ledger proposal --run-dir <dir>` prints the newest unanswered proposal in plain
     short sentences (idea by idea: the plain sentence first, then family, direction, reason),
     how long the loop will wait, and the exact reply command.
   - `alpha ledger reply --run-dir <dir> --as owner|stand-in [--accept NAME]... [--drop NAME[=reason]]...
     [--revise NAME=note]... [--idea "text"]... [--note "text"]` writes a valid `reply.json`
     atomically. Unmentioned ideas default to `accept`. `--as stand-in` writes the exact author
     string `stand-in user, not the owner`. Unknown idea names are refused with the list of
     names.
4. **Honesty rules that must not change:** every threshold, cap, pass rule, family failure
   limit, how tested ideas are counted, the reserved-window rule, gateway budgets. A user idea
   gets no easier test than an agent idea. The reply can never approve, admit or promote
   anything; it only chooses what gets built and tested.
5. **Tests** (fail first; use the existing fakes; no real provider, no sleeping): pause writes
   the proposal and builds nothing before a reply; accept / drop / revise / user idea each do
   exactly the above; a dropped idea adds no ledger row and no family failure; the extra call
   is counted and the cap path works; invalid reply is set aside and waiting continues; timeout
   `proceed` and `stop`; `--discuss` absent reproduces today's round record except for the
   additive fields (show that removing them restores the old bytes); `plain_summary` validation
   cases; the two commands' printed text and the written file; the journey step 1 sentence.
6. Update `workers/rdagent/README.md` (a short "Propose and discuss" section with the two
   commands), `workers/rdagent/CONTEXT.md`, the RD-Agent component page (≤ 200 lines: trim to
   add; mark "pause on the Workstation screen" as not built), the journey tool card, and the
   capability record. Nothing is replaced by this change, so nothing is deleted: say so.

## Files

Edited:
- `workers/rdagent/factor_loop_launch.py`
- `workers/rdagent/factor_loop_entry.py`
- `workers/rdagent/alpha_factor_hypothesis.py`
- `workers/rdagent/research_memory.py`
- `apps/alpha-cli/src/alpha_cli/ledger_cmds.py`
- `apps/alpha-cli/src/alpha_cli/_rdagent_ledger.py`
- `apps/alpha-cli/src/alpha_cli/rdagent_journey_words.py`
- `workers/rdagent/README.md`
- `workers/rdagent/CONTEXT.md`
- `docs/reference/project/components/rd-agent.md`
- `research/tools/rdagent-journey.md`
- `docs/roadmap/capabilities.toml`

New:
- `workers/rdagent/discussion.py`
- `apps/alpha-cli/src/alpha_cli/rdagent_discussion.py`
- `tests/unit/test_rdagent_discussion.py`
- `tests/unit/test_rdagent_discussion_commands.py`

This decision overrides the standing rule for: other files under `workers/rdagent/` except
those under Do not touch; `apps/alpha-cli/src/alpha_cli/` modules whose name contains `rdagent`
or `ledger`; existing `tests/unit/test_rdagent_*.py` files and `tests/unit/_rdagent_support.py`;
generated pages, the capability trace and the triage sheet the capability and command tests
require (regenerate generated pages with their scripts); any living document
`scripts/fs.py stale` reports because of your edits (verify with a real text change or
`--reason`). The worker cannot import `alpha_cli`: the two sides share only the JSON files, and
the reply schema is defined once in the worker module and checked on the CLI side by a small
duplicate validator whose test proves the two accept and reject the same fixture set. If a
named file does not exist, use the real one. List each in the report; do not stop to ask; where
a rule is open choose the more cautious reading and state it.

## Do not touch

- `workers/rdagent/loop_guard.py`, `workers/rdagent/model_gateway.py` (read only),
  `tests/bias_guards`, `tests/oracles`, golden files, `.claude/`, `.agents/`, `.github/`,
  `.semgrep/`, `scripts/`, `uv.lock`, `packages/**`, `apps/alpha-web/**`.
- Every threshold, cap, pass rule, family failure limit, counting rule, reserved-window rule.
- No `vars(`, `__doc__`, `inspect`, `.__dict__`, `# type: ignore`, `noqa`, `nosemgrep`.
  Functions ≤ 150 lines, files ≤ 1,500 lines (split a file at or near the limit); tests fully
  type-annotated; no test file named `*fixups*` or ending `_<N>.py`. No negative shifts. No
  wall clock in code under test without an injected clock.

## Checks

- `uv run pytest -q tests/unit/test_rdagent_discussion.py tests/unit/test_rdagent_discussion_commands.py`
- `uv run pytest -q tests/unit -k "rdagent or ledger or journey or code_size or filesystem or docs_links or capabilities or command"`
- `uv run pytest -q tests/bias_guards`
- `uv run python scripts/fs.py stale`
- `uv run python scripts/gate.py check --base origin/main`

## Report

The round flow with the pause, step by step, with the file written at each step. Per reply
choice: effect, what is recorded, the test. How the extra call is counted. The byte proof for
`--discuss` absent. The exact printed text of `alpha ledger proposal` for a two-idea example.
What happens on timeout. Every file outside the list. Open readings you chose. What is
unverified (no real loop was run).
