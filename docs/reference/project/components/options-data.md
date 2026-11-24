---
owner: project layer
sources:
  - packages/alpha-data/src/alpha_data/options/**
  - docs/reference/invariants/data-options.md
  - tests/unit/test_options_pricing.py
  - tests/unit/test_options_implied.py
  - tests/unit/test_options_priced_fixture.py
  - tests/unit/test_options_conventions.py
  - tests/unit/test_options_american.py
  - tests/unit/test_options_american_implied.py
  - tests/unit/test_options_derived.py
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

Step 2 of the [research loop](../overview.md#the-research-loop): data in, point in time. The solver (built 2026-11-19) gives
implied volatility and greeks. A later build adds derived series such as IV rank for the context strip. Those are context,
not signals.

## Intended design

- One neutral record set: contract identity, chain snapshot, quote and trade apart, provider greeks and computed greeks apart.
- A snapshot is known from its `known_at`. A read as of time t sees only snapshots known by t.
- Invalid data fails loud and names the field. Crossed quotes and zero IV are labelled, not hidden.
- Research reads are cut at the held-back boundary (the same reserve constant the other stores use) and say how many
  snapshots they hid. Forward use (paper following, "active today", display) reads the newest data through a separately named
  reader, and a structural guard keeps research code off it.
- A seeded fixture adapter gives tests a chain with a known volatility surface. A provider adapter implements `OptionsAdapter`.
- A solver turns a quote mid into implied volatility and greeks with Black-Scholes-Merton or Black-76 and stores them in the
  `computed` slot, apart from provider values. American-style contracts use a binomial tree. When it cannot solve, it says
  so in a typed result (price outside the bounds, volatility outside the search interval).

## What is real today

First build, 2026-11-19: records, validation, the file store with hashes, the point-in-time reader and the fixture adapter.
Rules: [options invariants](../../invariants/data-options.md). Everything is checked on synthetic data only.
No real option data has been read.

Second build, 2026-11-19: the implied-volatility and greeks solver for European contracts, checked against published values,
and a fixture priced by the same model so the solver recovers the known surface. Still synthetic only.

Third build, 2026-11-19: American-style pricing, greeks and implied volatility on a Cox-Ross-Rubinstein tree with early
exercise at every node and escrowed cash dividends (an approximation; see the invariants page). The solver now covers
listed US equity and ETF options as well as European index and futures options. The fixture has an American mode
priced by the tree. A solve costs about 0.14 s at 500 steps; a 100-contract chain with greeks about 21 s.

Not built:
- Health card rows; joining the derived series to the context store.
- Any provider adapter, history import, security-id map and delisted-name universe. These wait for the purchase.
- Derived series (`iv30`, rank, skew, term slope, IV minus RV) exist as `alpha options derived`; no screen shows them yet.

## Where it lives

- **Workspaces:** none (the code lives in the `packages/alpha-data` workspace, claimed by [data layer](data-layer.md))
- **Capabilities:** `options-data`
- Code: `packages/alpha-data/src/alpha_data/options/`.
- Tests: `tests/unit/test_options_schema.py`, `tests/unit/test_options_store.py`, `tests/unit/test_options_held_back.py`,
  `tests/unit/test_options_forward_guard.py`, `tests/unit/test_options_pricing.py`, `tests/unit/test_options_implied.py`,
  `tests/unit/test_options_priced_fixture.py`, `tests/unit/test_options_conventions.py`, `tests/unit/test_options_american.py`,
  `tests/unit/test_options_american_implied.py`, `tests/unit/test_options_derived.py`, `tests/unit/test_options_derived_cmd.py`.
- **Plan:** [stage 2](../../../roadmap/production-scope.md#2-data-and-context) of the checklist.
- How to change it: [packages/alpha-data/CONTEXT.md](../../../../packages/alpha-data/CONTEXT.md).

## Decisions and open questions

- Decided 2026-11-19: buy a paid data package, including options, in about a week; the provider is open.
- Open readings in the first build: crossed and zero-width quotes are labelled rather than refused; a snapshot file is named
  by its timestamp rather than its date; the placeholder fixture mode keeps its price shape, which is not arbitrage-free
  and must never judge a method; the model-priced mode is the one for solver tests. Theta is per calendar day, vega per 1.00 of
  volatility, ACT/365 fixed; convert a provider's units before comparing (see the [options invariants](../../invariants/data-options.md)).

## Never

- Never let a read see a snapshot before its `known_at`, or let a research read reach the held-back period.
- Never call the forward-use reader from research code.
- Never change a stored snapshot; a different version is a new snapshot or a loud refusal.
- Never mix provider greeks and computed greeks in one field.
- The rules: [options invariants](../../invariants/data-options.md).
