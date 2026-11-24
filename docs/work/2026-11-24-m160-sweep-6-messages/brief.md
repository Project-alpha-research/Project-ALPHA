# m160: sweep 6 message fixes

Goal: fix the plain-words gaps that acceptance sweep 6 found. Messages and defaults only; nothing that is computed changes.

- A test on bars that all lie in the held-back period says why, and what to do.
- `alpha provider check`: "no key set" (names the variable) instead of "schema_drift"; lists the providers that have a check.
- `alpha rdagent status` with no run folder names `--run-dir`; the run-viewer variables are in the card.
- `alpha context show*`: newest 20 rows by default, one shared helper (`context_rows.py`).
- Market view says "bars"; `data coverage` says viewing is not a test.
- Published-factor command says when the stored release is dated after the as-of date; the card example is corrected.
- `alpha ml run`: minimum assets with its reason; help names the feature version.
- Capability cards record the sweep (no numbers).

Not in scope: Kronos time estimate, Sharpe difference between commands, frozen try counts, ML "not clear of chance", AFML install, FRED key loading.
Protected: the viewer script is under `workers/`, so its own error text is not changed.
