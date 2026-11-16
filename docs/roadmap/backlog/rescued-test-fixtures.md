# Test-fixture ideas recovered from earlier material

**Status:** Idea
**Rough size:** M

## Problem / why

Checks that were specified in earlier plans but never written. This note records them as plans;
no test is added by it.

- A detector is checked against a hand-labelled set of examples before use.
- Mechanical data handling: alignment by key rather than position, join counts and null-key
  policy, group denominators with missing keys, time-bin membership versus label, daylight-saving
  gaps versus the time a value became known, training-derived state reused inside a fold, reshape
  round trips, histogram and density integrity.
- A broader acceptance catalogue: a stop and a target in the same bar and missing-bar policy;
  purging by the union of test-label intervals; detection of a rewritten or truncated attempt
  history; strict replay of a decision; damaged-artifact cases; drop-row accounting in factor
  selection; failure of a provider answer never read as "no event".
- First-study preflight: an independently written chronological fixture that catches a one-bar
  error both producer and replay share; a price-only reference line is not an executed control; a
  drawdown extreme between sampled points must stay discoverable; the 252-period year is a setting.

## Where it would live

`tests/oracles`, `tests/bias_guards` and [invariants](../../reference/invariants/data.md).

## What "done" looks like

Each fixture exists as a test, or the owner drops it.

## Dependencies

None.

## Sources

- [Checklist stage 2](../production-scope.md#2-data-and-context), [stage 3](../production-scope.md#3-look-before-testing)
