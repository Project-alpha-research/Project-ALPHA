# Brief: toolbox checks, family D. Overfitting and multiple-testing controls

Branch: `feat/toolbox-d-overfitting`. Module: `apps/alpha-cli/src/alpha_cli/toolbox/families/overfit_controls.py`. Tests: `tests/unit/test_toolbox_overfit_controls.py`.
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

## D. Overfitting and multiple-testing controls (26)

| # | Test | Question | Needs | Kind | Reference | ALPHA |
|---|---|---|---|---|---|---|
| D1 | Probabilistic Sharpe ratio | Probability that true Sharpe exceeds a benchmark? | R | G | Bailey & López de Prado 2012 | have |
| D2 | Deflated Sharpe ratio * | Is the Sharpe real after counting how many things were tried? | R + trial count | G | Bailey & López de Prado 2014 | have |
| D3 | Minimum track record length | How long a record is needed to trust this Sharpe? | R | G | Bailey & López de Prado 2012 | partial |
| D4 | PBO via CSCV * | How often does the in-sample winner rank poorly out of sample? | MS | G | Bailey, Borwein, López de Prado, Zhu 2017 | have |
| D5 | White's Reality Check | Does the best of many rules beat the benchmark beyond chance? | MS | G | White 2000 | have·code |
| D6 | Hansen SPA test | Same, with less loss of power to bad rules | MS | G | Hansen 2005 | have·code |
| D7 | Romano-Wolf stepdown (StepM) | Which individual rules are significant, controlling family-wise error? | MS | G | Romano & Wolf 2005 | missing |
| D8 | Bonferroni correction | Adjust p-values for number of tests, strictly | p-values | G | | missing |
| D9 | Holm step-down | Same, less conservative | p-values | G | Holm 1979 | partial |
| D10 | Benjamini-Hochberg FDR | Which findings hold at a false-discovery rate? | p-values | G | Benjamini & Hochberg 1995 | have |
| D11 | Benjamini-Yekutieli FDR | FDR under dependence | p-values | G | Benjamini & Yekutieli 2001 | missing |
| D12 | Storey q-values | Adaptive false-discovery estimate | p-values | G | Storey 2002 | missing |
| D13 | Haircut Sharpe ratio * | How much should this Sharpe be cut for multiple testing? | R + trial count | G | Harvey & Liu 2015 | missing |
| D14 | Minimum backtest length * | How many years are needed given the number of trials? | trial count | G | Bailey et al. 2014 | missing |
| D15 | False strategy theorem / expected max Sharpe | What best Sharpe would pure noise reach with N trials? | trial count | C | Bailey & López de Prado 2...
| D16 | Trial counting / ledger * | How many ideas and variants were tried? | ledger | D | | have |
| D17 | Effective number of independent trials | Are the N trials really N, or clusters of copies? | MS | D | López de Prado 2018 (ONC) | missing |
| D18 | In-sample MCPT | Does the optimised best beat permuted data tuned the same way? | B + params | G | Aronson 2006 | have |
| D19 | Out-of-sample degradation / WFE | How much return survives out of sample versus in sample? | RUN | D | Pardo | have |
| D20 | IS-OOS rank correlation | Do in-sample winners tend to win out of sample? | MS | D | | missing |
| D21 | t-stat hurdle (≈3) | Is the t-stat above the multiple-testing hurdle? | R | G | Harvey, Liu, Zhu 2016 | missing |
| D22 | Sample-size gate (≥30 trades) * | Is the sample big enough for any claim? | T | G | | have |
| D23 | Power / required-N analysis | How many observations to detect the effect? | R | D | | have·code |
| D24 | Frozen pre-registered spec hash | Was the test fixed before the result was seen? | spec | C | | have |
| D25 | Sequential testing / alpha spending (SPRT) | Can we stop early without inflating error? | R/T | G | Wald 1945 | missing |
| D26 | Bayesian shrinkage of Sharpe | What is the Sharpe after shrinking toward a sceptical prior? | R + trial count | D | Harvey & Liu 2018 | missing |

