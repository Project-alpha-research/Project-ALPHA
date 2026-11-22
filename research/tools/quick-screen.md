---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/_hypothesis_scan.py
  - apps/alpha-cli/src/alpha_cli/_screen_trials.py
  - apps/alpha-cli/src/alpha_cli/scan_cmds.py
verified: 9bab39f345a7e8c9
---

# Quick screen

**Reach for it when** you want a first look at many signals over a frozen set of assets. It is a first look, not a test.

**Commands**
```text
alpha scan hypotheses --as-of 2020-04-09 --symbols A,B,C --snapshot <SNAPSHOT> --signals rev_1m --horizons 1,5,10
alpha scan replay <scan_id>
```

**How to read it**
- Each row is one signal at one horizon: mean rank correlation (IC) with its t statistic, the top-minus-bottom spread, the spread after cost and turnover.
- The t statistics are plain. Horizons over 1 overlap and are not corrected. Nothing is adjusted for the number of tries.
- Every hypothesis counts as one try on each asset in the screen, in the one trial ledger. The screen says how many tries it added.
- The same screen on the same data counts once. A replay adds no tries, unless the screen was stored before screens counted: then the replay counts it once.
- A later `alpha test` on one of these assets counts the tries, so its deflated Sharpe is lower than if the screen had not run.
**What it cannot tell you**
- Whether any signal works after costs and out-of-sample. A screen has no return stream and no deflated Sharpe.
- Anything about the held-back period: the screen reads only up to the cut-off.
**Next** Take one signal you still care about to [a rule test](rule-test.md). The tries of this screen already count against it.
