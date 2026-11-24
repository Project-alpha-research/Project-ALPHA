# m159: a test leaves a process alive (shard 4 on main)

## Problem
CI job `tests (4/4)` on main passed all tests, then `scripts/run_owned_test.py` printed
`command left live descendants` and exited 1.

## Cause
`alpha_cli.nightly_alert.notify` ran the desktop notifier with `subprocess.run(timeout=...)`.
On a timeout it killed only the notifier. A child the notifier had started (a `sleep 30` in the
test's fake `notify-send`) stayed alive for 30 seconds. The test
`test_a_hanging_notifier_is_stopped_and_changes_nothing` left that child. It was harmless
unless the test ran near the end of a shard. Removing test files reshuffled the shards and put
the file into shard 4.

## Fix
`notify` starts the notifier in its own process group and kills the whole group when the wait ends.
The test now asserts that the notifier's own child is gone.

## Proof
Before: `run_owned_test.py -- pytest tests/unit/test_nightly_alert.py` printed the message and
exited 1. After: exit 0, no message, twice.
