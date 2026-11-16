# Exact versions for outside projects in the main install's manifests

**Status:** Idea
**Rough size:** S

## Problem / why

Rule 4 of the glue rules asks for exact versions with checksums, and an upgrade as its own pull
request. The main install meets the first half only through `uv.lock`: most `pyproject.toml`
files under `packages/` and `apps/` give ranges (`pandas>=2.0`, `polars>=1.0`, `ccxt>=4.0`); only
NautilusTrader, exchange_calendars and webauthn are exact. So refreshing the lock for one
library can move many others in the same change, and nothing forces a side-by-side check.

## What "done" looks like

Each outside project named *In use* in the register has an exact version in the manifest of the
package that imports it, matching `uv.lock`; a test fails when a manifest range and the lock
disagree or a new range appears; the lock is still installed only with `uv sync --locked`. The
first upgrade after that is one library in one pull request with its comparison recorded.

## Dependencies

Touches the root `uv.lock`, which is approval-bound while a real study is pending. No behaviour
change is intended: the resolved versions stay the ones in the lock today.

## Sources

- [ADR-0051](../../adr/0051-glue-rules-for-outside-projects.md) (rule 4)
- [Outside projects register](../../reference/project/outside-projects.md)
