# Coverage maps for Qlib and RD-Agent

**Status:** Idea
**Rough size:** M

## Problem / why

The owner wants everything the engines offer, each item with an honest state, never silently
dropped ([adopt everything RD-Agent has](../../reference/project/owner-decisions-3.md#2026-11-15-adopt-everything-rd-agent-has-memory-first)).
Private research listed what Qlib's own guide advertises (about 28 items, with reinforcement
learning and online serving open) and RD-Agent's wider scenario families (paper to model,
general data science, fine-tuning, a reinforcement-learning bench). Neither list is in the repo.

Also open: the worker and command line write machine-learning results in a newer schema (a
ranked ensemble, two fits) than the web models read; check before the results screen uses them.
Known limits of the RD-Agent judge, from pull request 172: its replay is ALPHA's own engine, not
Nautilus; it is long-only, so a factor's losing side is invisible; the quick-screen inference is
calibrated on independent noise only. An intake checklist for new upstream versions (pins,
images, fixtures re-run) is also wanted.

## Where it would live

Two tables in [rd-agent-in-alpha.md](../rd-agent-in-alpha.md) and the Qlib component page.

## What "done" looks like

Each advertised item listed as in scope, later or out, with its reason; the schema check done.

## Dependencies

None.

## Sources

- [Checklist stage 9](../production-scope-2.md#9-rd-agent-and-qlib-engines)
