---
owner: command line advisory assistants
sources:
  - apps/alpha-cli/src/alpha_cli/assistant_*.py
  - tests/unit/test_assistant_*.py
verified: 14830c29f5e4c510
---

# Command line assistant invariants

What must not break when changing the advisory model surfaces: `alpha assistant` sessions, which are advisory. Project-wide rules:
[research integrity § Models and isolated workers](research-integrity.md#models-and-isolated-workers) and
[research integrity § Owner authority](research-integrity.md#owner-authority).

## No authority

- Assistant sessions never admit evidence, run generated code or exercise owner authority.
- The browser supplies identifiers only, never evidence or filesystem paths (`assistant_contracts.py`). Context is resolved by the CLI (`assistant_context.py`).
- `assistant create|show|turn|check` are owner-only in generic launch classification; the web adapter calls this
  closed CLI vocabulary.

## Assistant sessions

- Model tools are disabled; the prompt states the model has no tools or execution authority (`assistant_runtime.py`).
- One inference runs at a time and is bounded by cancellation and a five-minute limit (`TIMEOUT_SECONDS = 300`).
- The session's context hash is re-checked before a draft is used (`assistant_service.py`); a changed context fails.
- A model reply must be exactly `text`, `citations` and `rule_draft`. Every citation must name a reference in the
  server-built context, and a `rule_draft` must parse through `alpha_strategies.rules`; it stays a draft.
- The session journal is separate from admitted research evidence.
- A session created with `rules_sha256` fails context resolution, at creation and on every `check`, when
  `alpha rules explain` reports a different hash for the saved rule; rerun the scan or choose the current rule.

## Cleanup and the global lock

- The watchdog (`assistant_worker.py`) runs outside the model process group and keeps the inherited global lock until
  cleanup completes. Parent loss, deadline and owner cancellation signal the model group, reap the direct child, and
  wait for the group to disappear before the lock is released.
- Caller cancellation asks the watchdog to stop and waits; never kill the lock holder first.
- Never send a destructive group signal after the leader is reaped, and never reuse a PID already reaped by
  `communicate()` to authorise another group signal.
- If the OS cannot reap a group, cleanup stays blocked. That is fail-closed, not a promise that shutdown ends in five
  minutes. Detached processes, and an external kill of the watchdog itself, are not contained. Enforced by `tests/unit/test_assistant_cleanup.py`.
