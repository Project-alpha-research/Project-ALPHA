---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/spine/setup_trade.py
  - apps/alpha-cli/src/alpha_cli/spine/setup_exits.py
  - apps/alpha-cli/src/alpha_cli/spine/setup_costs.py
  - apps/alpha-cli/src/alpha_cli/spine/setup_controls.py
  - apps/alpha-cli/src/alpha_cli/spine/setup_trade_figure.py
  - apps/alpha-cli/src/alpha_cli/setup_cmds.py
verified: 4ec2fbbae33384e0
---

# Setup trade

**Reach for it when** the recorded matches are right and the question includes stops or targets.

**Commands**
```text
uv run alpha setup trade <find_id> --json
uv run alpha results cite <trade_id> setup_trade_mean_net_return --json
```
**See stored results:** Workstation → Research → Setup Lab.
**How to read it**
- Put `[exit]` in the spec before finding: stop/target as percent, ATR distance or a causal
  numeric expression (or a named reference), plus `time_bars` (none: 250, `no-time-exit`) or `opposite`.
- Levels freeze at the trigger close. Entry is the next open. Stop wins a both-touch bar;
  stop gaps fill at the open; target gaps receive only the target. Opposite fills next open.
- One position per asset; skipped, invalid and still-open trades are counted, never averaged.
- Compare the mean with the same exits on every eligible date and 2,000 spaced random draws.
  Each chronological half uses its own dates. Missing controls have a reason, never zero.
- Stocks/ETFs pay 1 bp fee plus 2 bp slippage per side; crypto pays 10 plus 5. The market comes
  from the stored data's identity or provider; an unknown one uses crypto costs with
  `costs-assumed-high`. Costs per asset are in the summary.
- Figure: one bar per trade (red stop, green target, blue time), then the mean vs random dates.
- One counted test; repeats do not count. Changed exits mean another find and counted test.

**What it cannot tell you** Sizing, short trades, dividends, funding, portfolios or confirmation
on reserved data. Unusual dates are not proof that the setup can be traded.

**Next** Cite the stored reading and labels; inspect the halves before proposing another test.
