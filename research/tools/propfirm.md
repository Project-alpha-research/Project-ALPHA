---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/propfirm_cmds.py
  - apps/alpha-cli/src/alpha_cli/_propfirm.py
---

# Prop-firm evaluation: pass and bust rates

**Reach for it when** the owner asks "could this rule pass a funded-trader evaluation?" or "how often would it blow the account?".
**Command**
```text
alpha propfirm run SPY --firm topstep          # a fresh backtest of SPY against a preset
alpha propfirm run --from-run <run id>         # the equity curve of a stored run, custom rules
alpha propfirm run SPY --firm apex --horizon 60 --profit-target 2500
```
Presets: `apex`, `takeprofit`, `topstep`; leave `--firm` out for the custom rules. An unknown name is refused with the list.
Any rule flag (`--profit-target`, `--max-drawdown`, `--daily-loss`, `--account-size`, ...) overrides the preset.
The output starts with the rules used: profit target, daily loss limit, maximum loss (trailing or fixed), time limit.
Then the evaluation length: 30 trading days by default (no preset sets a time limit), or `--horizon` days.

**How to read it**
- The daily returns are resampled in blocks (losing streaks are kept) into 5,000 short paths of that length.
- `pass` is the share of paths that reach the profit target first, after the minimum trading days.
- `bust` is the share that hit the daily loss limit or the maximum loss, in the evaluation or later in the funded phase.
- `payout` is the share that also earned a payout in the funded phase; `expected payout` is the average across
  every path, after the evaluation fee.
- A longer horizon raises both rates: over years a trailing drawdown is breached almost surely, so a run over the
  whole history (the old default) reads "bust 100%". Compare rules at the same length.
- Rates are shares of resampled paths of one past record. They move with `--seed` by a point or two at 5,000 paths.

**What it cannot tell you** Whether the firm's real rules match: the presets are approximate and change often; check
the firm's contract. Losses inside a day are invisible: limits are checked on end-of-day balances, so a real
intraday breach can come first. A short or lucky record gives rates that are too good. It is no advice and no promise.
**Next** A rule that busts often: look at [path risk](path-risk.md) and its drawdowns. A rule that passes often on a
short record: test it on more data with the [rule test](rule-test.md) first.
