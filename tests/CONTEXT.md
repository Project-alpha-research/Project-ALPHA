---
owner: root test suite
sources:
  - tests/_tiers.py
  - tests/conftest.py
  - tests/bias_guards/test_future_poison_pattern.py
  - tests/oracles/_reference/**
verified: 1d2618615517c493
---

# tests workspace

## Purpose

The root test suite for every package and app. The isolated workers keep their own suites.
Tests must never read the guarded `tests/holdout/`, and guards and oracles must never be weakened to make a change pass.

## Read first

| Read | Section | When |
|---|---|---|
| [testing invariants](../docs/reference/invariants/testing.md) | Test layers | always |
| [testing invariants](../docs/reference/invariants/testing.md) | Markers and tiers | always |
| [research integrity](../docs/reference/invariants/research-integrity.md) | Protected and hidden tests | always |
| [testing invariants](../docs/reference/invariants/testing.md) | — | adding a bias guard, an oracle or an owned process |
| [checks](../docs/reference/checks.md) | — | adding a marker or moving tests between CI tiers |
| [research integrity](../docs/reference/invariants/research-integrity.md) | Statistical evidence | writing tolerances for statistics |
| [what this part is for](../docs/reference/project/components/delivery-and-agent-tooling.md) | — | why it exists; before you keep, shelve or remove it |

## How to change it

- Layout and run commands: [test layers](../docs/reference/invariants/testing.md#test-layers),
  [markers and tiers](../docs/reference/invariants/testing.md#markers-and-tiers).
- Protected (reviewed pull request only): `tests/bias_guards/`, `tests/oracles/`,
  `tests/unit/test_claude_harness_*.py`, `tests/_tiers.py`, `tests/acceptance/`.

## Outputs

- The test, in the layer its subject belongs to: [test layers](../docs/reference/invariants/testing.md#test-layers).
- The owning document: `docs/reference/invariants/testing.md`.
