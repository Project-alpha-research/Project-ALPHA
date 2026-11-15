# Name where NautilusTrader may be imported

**Status:** Idea
**Rough size:** S

## Problem / why

Rule 5 of the glue rules puts a heavy engine in its own worker and a light library inside one
package; rule 6 asks for one thin adapter. NautilusTrader is a large compiled engine imported
directly by three packages (`alpha-backtest`, `alpha-strategies`, `alpha-cli`), at one exact
version. It agrees with ALPHA's pins and the harness needs it in the same process, so a worker is
probably the wrong answer; but today nothing written says which packages may import it, and
nothing stops a fourth.

## What "done" looks like

A recorded choice between two options: keep the direct import as a named exception to rule 5,
with an import rule in the root `pyproject.toml` that lists the only packages allowed to import
`nautilus_trader`; or narrow the imports to `alpha-backtest` as the one adapter. Either way a
test fails when a package outside the list imports it, and the
[Nautilus page](../../reference/project/components/nautilus.md) states the choice.

## Dependencies

None for the first option. The second moves strategy base classes and is a refactor of its own.

## Sources

- [ADR-0051](../../adr/0051-glue-rules-for-outside-projects.md) (rules 5 and 6)
- [Backtest workspace](../../../packages/alpha-backtest/CONTEXT.md)
