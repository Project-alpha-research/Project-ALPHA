# Build report: m21-two-flaky-tests

## Changed files

- Forced the gateway startup race with a barrier and kept the real-server case. [tests/unit/test_rdagent_factor_launch.py](tests/unit/test_rdagent_factor_launch.py:515)
- Used a CSV fixture and a standard-library child for the look-ahead test. [tests/unit/test_rdagent_factor_judge.py](tests/unit/test_rdagent_factor_judge.py:965)
- Added a socket-free harness that runs the real gateway startup and shutdown code. [tests/unit/_rdagent_support.py](tests/unit/_rdagent_support.py:77)
- Sent `SIGINT` to the gateway so Python runs its cleanup before the gateway installs its `SIGTERM` handler. [workers/rdagent/factor_loop_launch.py](workers/rdagent/factor_loop_launch.py:573)
- Re-verified the worker instructions and invariants and recorded the reasons. `workers/rdagent/CONTEXT.md`, `docs/reference/invariants/workers.md`, `docs/verified-reasons.txt`

## Checks

| Command | PASS / FAIL / UNVERIFIED | Exit code |
|---|---|---:|
| `PYTHONPATH=/tmp/alpha-m21-tools uv run pytest -q -p m21_repeat G J -k 'forced-race or real_whole_panel'` | PASS · 50 per test | 0 |
| Same command with `-p xdist -n 4` | PASS · 50 per test | 0 |
| `uv run pytest -q` on the launcher and judge files, socket-free selection | PASS · 72 passed, 3 skipped | 0 |
| `uv run pytest -q tests/unit -k "rdagent or code_size or filesystem"`, sandbox selection | FAIL · 1,107 passed, 27 failed, 45 errors, 25 skipped | 1 |
| `uv run pytest -q tests/bias_guards` | PASS · 207 passed, 4 skipped | 0 |
| `uv run python scripts/fs.py stale --strict` | PASS · 0 stale | 0 |
| `uv run python scripts/gate.py check --base origin/main`, socket-free selection | PASS | 0 |
| `uv run ruff check` and `uv run ruff format --check` on changed Python files | PASS | 0 |
| `uv run mypy` on changed Python files | PASS | 0 |

`G` and `J` stand for the full pytest node IDs of `test_runs_sharing_one_gateway_state_each_get_their_own_gateway` and `test_real_whole_panel_peek_is_reproducible_lookahead`.

- **Gateway product defect.** `SIGTERM` could arrive after session publication and before handler installation, leaving the PID-specific file behind. The forced ordering failed 50/50 before the fix and 0/50 after it. The test still checks that three concurrent launches get their own endpoints and tokens, stopping one preserves the others, and final shutdown removes every session file.
- **Judge fixture defect.** Under CPU contention, the pandas and Parquet child exceeded the existing 30-second deadline. The stressed test failed 8/8 before the fix and 0/8 after it. The baseline passed 50/50 both serially and with xdist without injected load. The updated test still checks that a whole-panel mean changes the prefix, returns `LOOKAHEAD`, and reproduces the result in two real child runs.

## UNVERIFIED

The live gateway cases, viewer socket case, native supervisor socket case, and FastAPI `TestClient` case need an unrestricted run. Two in-process web cases stalled in the sandbox and were excluded from the completed broad run. The broad run also hit gateway validation failures because of the pre-existing `/tmp/.git` marker. The skipped RD-Agent and AFML cases require their external runtimes. Natural CI failure rates remain unverified.

## Deviations

The repetitions used a temporary pytest plugin outside the worktree. A verification-only shim hid the sandbox’s `/tmp/.git` marker for the forced gateway child. The broader checks retained normal gateway validation.

## Questions

None.

## Review corrections

The review replaced both fixes.

- **Look-ahead test.** The 30-second deadline was not the cause. Under load the Parquet child
  sometimes aborted at exit (exit -6, "terminate called without an active exception" from
  pyarrow threads). The CSV and standard-library child dropped the pandas factor. The test now
  keeps the pandas child and uses pickle in place of the unavailable HDF writer.
- **Gateway test.** `SIGINT` is ignored by a child started from a background shell, so that
  gateway would never stop cleanly. The launcher keeps `SIGTERM`. It now removes the gateway's
  session files after the gateway stops, only while they carry this run's token. This also
  covers a gateway killed after the 10-second wait.
