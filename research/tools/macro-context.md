---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/context_cmds.py
  - apps/alpha-cli/src/alpha_cli/spine/macro.py
---

# Macro context

**Reach for it when** a loss or a gain lines up with a market period and the question is "what was the
economy doing then?": rates, the yield curve, volatility, credit spreads, unemployment.

**Commands**

```text
alpha context list --json
alpha context window --start 2022-01-03 --end 2022-10-12 --json
alpha context show DGS10 --start 2022-01-01 --end 2022-12-31 --json
```

**How to read it**

- `alpha context list` shows which series are stored. Nothing stored: the owner downloads them with
  `alpha context pull` (it needs the owner's free FRED key; never ask for the key or type it yourself).
- `alpha context window` gives, per series, `start_value`, `end_value`, `change`, `min` and `max` for the
  dates you name, as known at the end of the window (`as_of`). Use the dates of a drawdown from
  `drawdowns.episodes` in [diagnose and audit](diagnose-and-audit.md).
- `macro_window` inside `alpha diagnose` already does this for the worst drawdown, as known on its trough
  date, with `start_value`, `trough_value` and `change`. `available: false` with a `reason` means no series are stored or no drawdown.
- `show` lists one series' observations as known at `--as-of` (default today); the `--view` it used is named in the output.

**What it cannot tell you**

- Cause. A rate rise during a drawdown is a coincidence until a test separates it: say "Hypothesis:".
- Regimes or market states: see [regimes](attribution-regimes-changepoints.md). These numbers are not covered by
  `alpha results cite`; quote them with the command, the dates and the series id.

**Next** Test the leading explanation: the same rule on a second asset or a different period with the
[rule test](rule-test.md).
