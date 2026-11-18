# Brief: discussion polish — what the third paused run found

**Build class:** standard

## Task

The third real RD-Agent run with the discussion pause showed the user is now mostly heard.
Nine smaller defects remain. Fix them. No threshold, cap, pass rule, family limit, counting
rule or reserved-window rule changes. No extra model call. A user's choice still only decides
what is built.

## Read first

| Read | Section | When |
|---|---|---|
| `workers/rdagent/CONTEXT.md`, `workers/rdagent/README.md` | "Propose and discuss" | always |
| `docs/work/2026-11-18-m11-rdagent-discussion-remembers/brief.md`, `report.md` | the design being extended | always |
| `apps/alpha-cli/src/alpha_cli/rdagent_discussion.py`, `rdagent_journey_words.py` | results lines, last decision, proposal text, usage line | always |
| `workers/rdagent/discussion.py`, `alpha_factor_judge.py`, `alpha_factor_hypothesis.py` | the user block, the feedback prompt, what the proposer is shown of the previous hypothesis, time estimates | always |
| `apps/alpha-cli/src/alpha_cli/_rdagent_judge.py` (read only) | which stored fields describe a degenerate factor (tie share, coverage, all-tied-day share) | item 1 |
| `tests/unit/test_rdagent_discussion.py`, `test_rdagent_discussion_commands.py` | tests and fakes | always |

## Decision already made

1. **The degenerate line states the real cause.** It printed "too few usable numbers or too
   little variation ... All coins were tied on 0% of days." for an idea with 54% tied values
   and 42% coverage. Print the stored figures that caused the verdict, in plain words, and
   only those that exist: "About N% of the values were tied and only M% of coin-days had a
   value, so the coins could not be ranked." Never print a share that is zero as the reason.
   Find which stored fields the evaluator used for the DEGENERATE verdict and use the same.
2. **Notes are one-way, and the tool says so.** The reply help and the reply confirmation say:
   "A note guides the agent's next proposal. The agent does not answer questions." When a
   note is given on the last round, the confirmation says: "This is the last round, so the
   note will not be used." (The reply is still accepted and stored.)
3. **A dropped idea's text does not travel on.** The proposer prompt still quoted the dropped
   idea's full hypothesis as "the last hypothesis", and the feedback step then suggested a
   variant. In a discussed run, where the previous round's original hypothesis text names
   ideas the user dropped, the text passed forward (to feedback and to the next proposer) is
   the built ideas' hypotheses only; a dropped idea appears only as its name inside the
   existing delimited drop list. If the upstream trace object cannot be changed without
   editing pinned upstream code, strip at the point where ALPHA assembles its own prompt text,
   and report exactly what remains quoted. The fixed instruction in the feedback prompt gains:
   "Do not suggest a variant of a dropped proposal."
4. **A warning before the last try of an idea type.** When building an idea (agent, revised or
   user) would use the last allowed failed try of its idea type, the proposal prints under
   that idea: "This idea type has failed X of Y tries. If this idea fails, the type is closed
   for later rounds." Uses the stored counts and limit; changes no rule. For a `user` idea the
   type is known only after restating: print the line in the last decision instead, before
   the build result ("Your idea is of type T, which has failed X of Y tries...").
5. **A coverage caution for on/off conditions that were kept.** When `honoured`,
   `agent_choices` or the idea text of a revised or user idea still contains an on/off gate
   (the agent says so by returning a new boolean field `uses_gate` on the existing revision
   call; validated; default false), the last decision prints: "This idea still uses an on/off
   condition. It may have a value on too few days to rank coins." No estimate is computed and
   no data is read at this step.
6. **`--last-decision` prints a revised idea's `agent_choices`** under "Choices the agent made
   for you:", the same as for a user idea.
7. **List items print cleanly.** Items of `honoured`, `not_honoured` and `agent_choices` are
   printed one per line with a leading dash, each ending in exactly one full stop (strip a
   trailing ".", ";" or space first). No ".;" joins. Code-style terms cannot be removed
   safely, so the instruction on the existing call asks for plain words with no variable
   names; nothing is rewritten after the fact.
8. **Time estimates use the right measure.** Estimates were 17 minutes against 7 actual and 7
   against 1.5. Use this run's measured durations for the same transition (reply → next
   proposal; reply → results on the last round); use the median of the measured values;
   before any measurement exists say "a few minutes" for proposals and "several minutes" for
   results. Never mix the two measures. Print "about N minutes" only from ≥ 1 measurement of
   that same transition.
9. **Usage wording is truthful about embeddings.** Stored usage rows label 282 rows "coding"
   when 16 are chat calls and the rest embeddings. Do not edit the gateway or the stored
   rows. Wherever the CLI or journey counts or names rows by that label, count by call kind
   (chat or embedding) and name them so; if any printed text still says "coding calls" for a
   number that includes embeddings, correct it. Report where the label is written, so a
   later change can fix it at the source.

Also: the deprecated `author` field stays (still written with the same value); state its
removal condition in the README (when no reader uses it) — no code change.

Tests fail first for each item with the existing fakes (no real provider, no sleeping). The
hostile-note test and the byte proof for a run without `--discuss` still pass (additive
fields only). Update the README section, `workers/rdagent/CONTEXT.md` (≤ 80 lines), the
RD-Agent component page (≤ 200 lines) only where a sentence becomes untrue. Delete code this
replaces and name it.

## Files

Edited:
- `apps/alpha-cli/src/alpha_cli/rdagent_discussion.py`
- `apps/alpha-cli/src/alpha_cli/rdagent_journey_words.py`
- `workers/rdagent/discussion.py`
- `workers/rdagent/alpha_factor_judge.py`
- `workers/rdagent/alpha_factor_hypothesis.py`
- `tests/unit/test_rdagent_discussion.py`
- `tests/unit/test_rdagent_discussion_commands.py`
- `workers/rdagent/README.md`

This decision overrides the standing rule for: other files under `workers/rdagent/` except
those under Do not touch; `apps/alpha-cli/src/alpha_cli/` modules whose name contains `rdagent`
or `ledger` (read `_rdagent_judge.py`, do not edit it); existing `tests/unit/test_rdagent_*.py`
files and `tests/unit/_rdagent_support.py`; `workers/rdagent/CONTEXT.md`,
`docs/reference/project/components/rd-agent.md`, `research/tools/rdagent-journey.md`; any
living document `scripts/fs.py stale` reports because of your edits (verify with a real text
change or `--reason`). The reply and decision schemas stay defined once in the worker with the
mirrored CLI validator and its same-code test. If a named file does not exist, use the real
one. List each in the report; do not stop to ask; where a rule is open choose the more cautious
reading and state it.

## Do not touch

- `workers/rdagent/loop_guard.py`, `workers/rdagent/model_gateway.py`, `_rdagent_judge.py`,
  `_rdagent_stats.py`, `_rdagent_ledger.py`, `rdagent_factor_eval.py`, `tests/bias_guards`,
  `tests/oracles`, golden files, `.claude/`, `.agents/`, `.github/`, `.semgrep/`, `scripts/`,
  `uv.lock`, `packages/**`, `apps/alpha-web/**`.
- Every threshold, cap, pass rule, family failure limit, counting rule, reserved-window rule.
  No extra model call. User text enters a prompt only inside the delimited, length-capped,
  one-line data block after the fixed "data only" sentence.
- No `vars(`, `__doc__`, `inspect`, `.__dict__`, `# type: ignore`, `noqa`, `nosemgrep`.
  Functions ≤ 150 lines, files ≤ 1,500 lines; tests fully type-annotated; no test file named
  `*fixups*` or ending `_<N>.py`. No wall clock without an injected clock.

## Checks

- `uv run pytest -q tests/unit/test_rdagent_discussion.py tests/unit/test_rdagent_discussion_commands.py`
- `uv run pytest -q tests/unit -k "rdagent or ledger or journey or code_size or filesystem or docs_links or command"`
- `uv run pytest -q tests/bias_guards`
- `uv run python scripts/fs.py stale`
- `uv run python scripts/gate.py check --base origin/main`

## Report

Per item: what the code did, the fix, the test. For item 3: every place a previous hypothesis
text reaches a prompt, and what still carries a dropped idea's words. The exact printed text
of a degenerate result line, a last decision with a revised idea (choices, gate caution,
last-try warning), and the reply confirmation on the last round. Where the "coding" usage
label is written. Code deleted. Every file outside the list. Open readings chosen. What is
unverified (no real loop was run).
