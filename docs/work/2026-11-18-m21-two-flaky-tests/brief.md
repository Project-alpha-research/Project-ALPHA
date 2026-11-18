# Brief: two tests fail now and then; find the cause and make them reliable

**Build class:** standard

## Task

Two tests fail on some CI runs and pass on a rerun. Every pull request pays for this with a
rerun, and a real fault could hide behind "it is the flaky one". Find the real cause of each
and remove it. Do not loosen what either test proves.

- `tests/unit/test_rdagent_factor_launch.py::test_runs_sharing_one_gateway_state_each_get_their_own_gateway`
- `tests/unit/test_rdagent_factor_judge.py::test_real_whole_panel_peek_is_reproducible_lookahead`

## Read first

| Read | Section | When |
|---|---|---|
| `tests/CONTEXT.md` | whole | always |
| the two tests and every fixture and helper they use (`tests/unit/_rdagent_support.py`) | whole | always |
| `workers/rdagent/CONTEXT.md` | gateway state, ports, subprocess start | always |
| the code under test that each test reaches (launcher gateway start; the judge's look-ahead probe) | the paths the tests run | always |

## Decision already made

1. **Cause first.** For each test, state the mechanism of the intermittent failure (for example
   a fixed or reused port, a race on a shared state folder, a wait with a deadline, dependence
   on wall-clock time, unseeded randomness, test order, parallel workers, a temp path that is
   too long for a Unix socket). Reproduce it: run the test many times (for example 50 runs, and
   under `-p xdist -n 4` if the suite uses it, and under CPU load) and record the failure rate
   before and after. If you cannot reproduce it, say so, and fix only causes you can show in
   the code (a race you can explain line by line); do not guess.
2. **Fix the cause, in the test or fixture where the fault is there, in the product code where
   the fault is there.** If the product code has a real race (two runs sharing one gateway
   state), that is a product defect: fix it within the files allowed below and add a test that
   forces the ordering deterministically (an event or barrier, an injected clock, an injected
   port), not a sleep.
3. **Not allowed:** retries or rerun markers, longer sleeps or longer timeouts as the fix,
   `skip`/`xfail`, weaker assertions, removing a case. The look-ahead test must still prove
   that a whole-panel peek is detected and that the result is reproducible.
4. No documentation change unless a sentence becomes untrue. If a known-flaky note exists in a
   living document, remove it in the same change.

## Files

Edited:
- `tests/unit/test_rdagent_factor_launch.py`
- `tests/unit/test_rdagent_factor_judge.py`
- `tests/unit/_rdagent_support.py`

This decision overrides the standing rule for: `workers/rdagent/factor_loop_launch.py` and
`workers/rdagent/alpha_factor_judge.py` and the helper modules they call under `workers/rdagent/`
(except those under Do not touch), only where the cause is a real defect there; any living
document `scripts/fs.py stale` reports because of your edits (verify with a real text change or
`--reason`). List each in the report; do not stop to ask; where a rule is open choose the more
cautious reading and state it.

## Do not touch

`workers/rdagent/loop_guard.py`, `workers/rdagent/model_gateway.py`, `packages/**`,
`tests/bias_guards`, `tests/oracles`, `.semgrep/`, `.github/`, `.claude/`, `.agents/`,
`scripts/`, `uv.lock`. Every threshold, cap and pass rule. No `nosemgrep`, `noqa`,
`type: ignore`, `vars(`, `__doc__`, `inspect`, `.__dict__`. Tests fully type-annotated; no test
file named `*fixups*` or ending `_<N>.py`. No wall clock in code under test without an injected
clock.

## Checks

- each of the two tests run 50 times in a row, all passing (state the command and the count)
- `uv run pytest -q tests/unit/test_rdagent_factor_launch.py tests/unit/test_rdagent_factor_judge.py`
- `uv run pytest -q tests/unit -k "rdagent or code_size or filesystem"`
- `uv run pytest -q tests/bias_guards`
- `uv run python scripts/fs.py stale`
- `uv run python scripts/gate.py check --base origin/main`

## Report

Per test: the mechanism, how you reproduced it (rate before), the fix, the rate after. Whether
the fault was in the test or the product. What each test still proves. Every file outside the
list. What is unverified.
