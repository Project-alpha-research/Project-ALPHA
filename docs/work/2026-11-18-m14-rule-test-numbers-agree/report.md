# Build report: m14-rule-test-numbers-agree

## Changed files

None in this follow-up.

## Checks

| Command | PASS / FAIL / UNVERIFIED | Exit code |
|---|---|---|
| `uv run python scripts/gate.py check --base origin/main` (external verification) | FAIL | 1 |

## UNVERIFIED

The sandbox prohibits socket tests, so I could not rerun the failing cases. The gate reported three failures. The supplied traceback confirms the cause for one of them.

## Deviations

None.

## Questions

Should the native fixture socket issue be handled separately? The traceback shows that `_Owner.open_control()` tried to bind `<temporary fixture root>/control/native-<UUID>.stop`, which exceeded Linux’s Unix-socket pathname limit. The native supervisor matches `origin/main` and falls outside the rule-test reporting brief. [Endpoint construction](apps/alpha-cli/src/alpha_cli/native_supervisor.py:215) · [Failing bind](apps/alpha-cli/src/alpha_cli/native_supervisor.py:312)
