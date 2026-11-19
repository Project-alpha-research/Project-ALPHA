---
owner: project layer
sources:
  - packages/alpha-data/src/alpha_data/options/**
  - docs/reference/invariants/data-options.md
verified: e235bd47f914eb5b
---

# Options data

The options data layer holds option chains from any provider in one shape, stores them without ever changing a stored
snapshot, and lets research read only what was known at a chosen time.

## Why it exists

Options show what the market expects, not only what it did. The owner decided on 2026-11-19 to buy a paid data package,
including options, in about a week; the provider is not chosen
([owner decisions](../owner-decisions.md)). The layer is built first so a provider can be plugged in later without
changing the records, the store or the checks.

## Its job in the research loop

Step 2 of the [research loop](../overview.md#the-research-loop): data in, point in time. Later builds add implied volatility
and greeks, then derived series such as IV rank for the context strip. Those are context, not signals.

## Intended design

- One neutral record set: contract identity, chain snapshot, quote and trade apart, provider greeks and computed greeks apart.
- A snapshot is known from its `known_at`. A read as of time t sees only snapshots known by t.
- Invalid data fails loud and names the field. Crossed quotes and zero IV are labelled, not hidden.
- Reads stop before the held-back period, through the same reserve constant the other stores use.
- A seeded fixture adapter gives tests a chain with a known volatility surface. A provider adapter implements `OptionsAdapter`.

## What is real today

First build, 2026-11-19: records, validation, the file store with hashes, the point-in-time reader and the fixture adapter.
Rules: [options invariants](../../invariants/data-options.md). Everything is checked on synthetic data only.
No real option data has been read.

Not built:
- Implied volatility and greeks solver, derived series, health card rows.
- Any provider adapter, history import, security-id map and delisted-name universe. These wait for the purchase.
- A command group. The fixture is not on any screen yet.

## Where it lives

- **Workspaces:** none (the code lives in the `packages/alpha-data` workspace, claimed by [data layer](data-layer.md))
- **Capabilities:** `options-data`
- Code: `packages/alpha-data/src/alpha_data/options/`.
- Tests: `tests/unit/test_options_schema.py`, `tests/unit/test_options_store.py`.
- **Plan:** [stage 2](../../../roadmap/production-scope.md#2-data-and-context) of the checklist.
- How to change it: [packages/alpha-data/CONTEXT.md](../../../../packages/alpha-data/CONTEXT.md).

## Decisions and open questions

- Decided 2026-11-19: buy a paid data package, including options, in about a week; the provider is open.
- Open readings in the first build: crossed and zero-width quotes are labelled rather than refused; a snapshot file is named
  by its timestamp rather than its date; the placeholder fixture price shape stands in until the solver build.

## Never

- Never let a read see a snapshot before its `known_at`, or reach the held-back period.
- Never change a stored snapshot; a different version is a new snapshot or a loud refusal.
- Never mix provider greeks and computed greeks in one field.
- The rules: [options invariants](../../invariants/data-options.md).
