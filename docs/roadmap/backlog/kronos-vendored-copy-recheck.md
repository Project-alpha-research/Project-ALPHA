# Re-check the vendored Kronos copy against the glue rules

**Status:** Idea
**Rough size:** S

## Problem / why

Rule 3 of the glue rules says never to edit upstream code, and rule 4 asks for an installed,
pinned package. Kronos is the one exception: two upstream model files are copied into
`packages/alpha-forecast/src/alpha_forecast/_vendor/kronos/` at a recorded commit, with a
documented rewrite of their import lines, because upstream published no installable package when
ADR-0008 was written. The exception is allowed only while that stays true, the copy differs from
upstream by nothing but the documented rewrite, and the licence file travels with it.

## What "done" looks like

Three things checked and written on the [forecasting page](../../reference/project/components/forecasting.md):
whether upstream now publishes a package with tagged releases (if so, plan the move to an
installed pin, with a side-by-side check of forecasts); a test that compares the copied files
with checksums of the upstream files at the recorded commit, apart from the rewritten import
lines; and the licence file present beside the copy.

## Dependencies

Reading upstream needs network access. `tests/unit/test_forecast_vendor.py` already covers part
of this; read it first.

## Sources

- [ADR-0051](../../adr/0051-glue-rules-for-outside-projects.md) (rules 3 and 4)
- [ADR-0008](../../adr/0008-vendored-kronos-and-alpha-forecast-layer.md)
