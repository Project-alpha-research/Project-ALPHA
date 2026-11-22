# Brief: toolbox checks, family G. Parameter and specification robustness

Branch: `feat/toolbox-g-parameters`. Module: `apps/alpha-cli/src/alpha_cli/toolbox/families/parameter_robustness.py`. Tests: `tests/unit/test_toolbox_parameter_robustness.py`.
Rules: `docs/work/2026-11-22-toolbox-common/brief.md` (read it fully first).

Build at least 10 and at most 14 new checks from this family of the catalogue. The table below is the catalogue section, copied as
research notes: its "ALPHA" column was a reading of the code on 2026-11-18 and may be out of date; check what exists before you build.

Legend:
## Legend

- **Needs:**
  - T = trades
  - R = return or equity series
  - B = price bars
  - F = factor or signal panel (date x asset, plus forward returns)
  - MS = multiple strategies or a trial set
  - ML = model or predictions
  - E = event list
  - X = extra data (macro, calendar, fundamentals, funding)
  - RUN = a finished alpha run
- **Kind:** D = diagnostic (describes), G = pass/fail test, C = control or baseline.
- **ALPHA:** have / partial / missing. Suffixes: ·code means a library function with no `alpha` command; ·dev means developer tests only.
- **Stars:** * marks the ones that matter most for a daily-bar swing trader with small size (43 in total).

---

## G. Parameter and specification robustness (20)

| # | Test | Question | Needs | Kind | Reference | ALPHA |
|---|---|---|---|---|---|---|
| G1 | One-at-a-time sensitivity * | Does moving each parameter a little break it? | rule | D | | have |
| G2 | Grid surface / heat map | What does performance look like across parameters? | rule | D | | partial |
| G3 | Plateau vs peak detection * | Is the best setting a wide plateau or a lone spike? | grid | D | | missing |
| G4 | Neighbourhood stability score | Do neighbours of the best setting perform similarly? | grid | D | | missing |
| G5 | Parameter stability over time | Does the best setting drift between windows? | rule | D | | missing |
| G6 | Specification curve | How does the result vary over all defensible choices? | rule + choices | D | Simonsohn, Simmons, Nelson 2020 | missing |
| G7 | Multiverse analysis | Same, across data-processing choices | rule + choices | D | Steegen et al. 2016 | missing |
| G8 | Feature ablation | What if each feature is removed? | model | D | | missing |
| G9 | Cost sensitivity (x2) | Does it survive doubled costs? | rule | D | | have |
| G10 | Delay sensitivity | Does it survive a one-bar delay? | rule | D | | have |
| G11 | Price-noise sensitivity | Does it survive small data noise? | rule | D | | have |
| G12 | Sweep trial accounting | Is every grid cell counted as a trial? | ledger | D | | have |
| G13 | Random-parameter baseline | How good are randomly drawn settings? | rule | C | | missing |
| G14 | Asset-subset / universe sensitivity | Does it depend on which assets? | B | D | | partial |
| G15 | Indicator-variant sensitivity (SMA/EMA/WMA) | Does swapping the indicator type matter? | rule | D | | missing |
| G16 | Lookback / horizon sweep | How does edge vary with window length? | rule/F | D | | partial |
| G17 | Rebalance-timing luck | Does shifting the rebalance day change results? | rule | D | Hoffstein, Faber, Braun 2020 | missing |
| G18 | Bar-sampling sensitivity (open vs close) | Does the evaluation bar matter? | B | D | | missing |
| G19 | Global sensitivity (Sobol indices) | Which parameters drive the variance? | rule | D | Sobol 1993 | missing |
| G20 | fANOVA / hyperparameter importance | Which tuning choices mattered? | trial set | D | Hutter et al. 2014 | missing |

