# Report: toolbox family G (parameter robustness)

Result: no check built. The brief cannot be met inside its own rules. This page says why and lists the options.

## Why

The brief says inputs come only from the shared loader and "if nothing does [re-run the engine], leave that check out".
I checked the code on `origin/main` (20d9337c).

1. `Inputs` gives stored equity, trades, benchmark and a `RunSeries` (dates, equity, opens, positions).
   It gives no bars, no `IdeaSpec` and no `RunSpec`. A check cannot re-run the rule with another parameter.
2. No toolbox check re-runs the engine. `costs.break_even` rescales stored per-bar costs. `robustness.start_end_dates` cuts stored equity.
3. The only parameter re-runs live in `spine/diagnose.py` (`variant_specs`, `price_noise`, `delay`). They run when the run is made.
   Their results sit in `diagnostics.json` (`sensitivity.variants`: one-at-a-time neighbours at 0.8x and 1.2x, plus costs x2).
   `diagnostics.json` is not a toolbox input kind and the runner does not hash it into the cache key. Reading it would break hash binding.
4. Re-reading bars inside a check is forbidden (`tests/unit/test_research_reads_are_cut.py`).

## Catalogue rows

| Row | Status | Reason |
|---|---|---|
| G1, G9, G10, G11, G12 | already covered | `have` in the catalogue; computed in `diagnose.py` |
| G2, G3, G4, G5, G6, G7, G13, G15, G16, G17, G19 | skipped | need a rule re-run with other settings; the loader has no bars or spec |
| G8, G20 | skipped | need a model or a trial set |
| G14 | skipped | needs other assets (extra data) |
| G18 | skipped | `RunSeries` holds opens only; no closes |

Rows G3 and G4 could be read from the stored neighbour variants, but that gives at most 2 checks, far below 10, and needs a new input kind.

## Options for the owner

1. Approve a small additive change to `toolbox/inputs.py` and `contract.py`: `RunSeries` also carries the bars, dividends, `IdeaSpec` and `RunSpec` that `load_run` already loads at the held-back cut.
   Then G2-G6, G13, G15-G17 and G19 can call `diagnose.variant_specs` and `full_sample`. Do this in one change before the other seven builders merge, to avoid conflicts.
2. Add `diagnostics.json` as a hashed input kind and build only G3 and G4.
3. Drop family G.

No code, tests or registry lines were changed. Nothing here weakens a guard.
