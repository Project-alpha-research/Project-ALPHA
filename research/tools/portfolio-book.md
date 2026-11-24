---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/spine/book.py
  - apps/alpha-cli/src/alpha_cli/results_cmds.py
  - apps/alpha-cli/src/alpha_cli/follow_cmds.py
verified: d8f3d6e402ae228f
---
# Portfolio book: several strategies together

**Reach for it when** two or more rule tests look good and the owner asks if they are the same bet, or how much paper size is in use.
**Command**
```text
alpha results correlate <run id> <run id> --json
alpha follow book --json
```

`results correlate` takes 2 to 8 rule-test runs. It reads only what each run stored: the walk-forward equity and the exposure.
It runs no test and reads no bar. `follow book` reads the follow records and journals. It writes nothing.

**How to read it**
- Each pair has one sentence: the correlation of daily returns, the number of common days, and the share of those days on which
  both runs were in the market.
- Near 1: the two runs rose and fell on the same days. Near 0: mostly independent. Near -1: opposite days.
- The returns are net of fees. Days out of the market count as zero. Days only one run has are dropped, and the sentence says how many.
- Under 60 common days the answer is "too few common days to read". No correlation is printed.
- "not defined" means the returns of one run do not change (for example, it never traded in the scored period).
- A run that saw the held-back period keeps its label and its sentence.
- `follow book` shows each active follow as a percent of ONE paper account, the total, and the sum per asset.
  Two follows of the same asset add up. "In the market now" counts only open paper positions.
- Above 100% it says "The follows together use N% of the paper account."

**What it cannot tell you** Whether the runs will move together later: this is the past, on the scored days only.
Correlation does not show a shared drop in a crisis. The book adds fixed paper sizes; it is not marked to market,
and each follow still keeps its own paper account. It gives no size to use and no advice.
**Next** A high correlation: read both runs with [benchmark and drawdowns](benchmark-and-drawdowns.md) before you count them as two ideas.
