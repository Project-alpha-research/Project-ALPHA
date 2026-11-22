---
owner: research pipeline
sources:
  - packages/alpha-study/src/alpha_study/setup/spec.py
  - apps/alpha-cli/src/alpha_cli/spine/setup_find.py
---
# Setup spec file

**Reach for it when** you write or fix the TOML file for [setup find](setup-find.md), [study](setup-study.md) or [trade](setup-trade.md).
A complete commented file: `research/examples/setup-spec.example.toml`. An unknown key is an error.

**Sections** Each row gives one example. Expressions read only bars known at that close.
| Section | Key and example |
|---|---|
| `[setup]` required | `name = "dip"`, `idea = "text"`, `assets = ["SPY"]`, `timeframe = "1D"`, `event = "crosses_above(close, sma(close, 10))"` |
| `[filters]` | `uptrend = "close > sma(close, 50)"`. All must be true. Order is kept: the first false one is the rejection reason |
| `[trigger]` | `when = "close > highest(high, 3)"`, `within = 2` bars after the event (0 = same day) |
| `[reference]` | `swing_low = "lowest(low, 5)"`. A named level read at the trigger close; drawn on the sheets; `[exit]` may use it by name |
| `[context]` | `es_pos = "cot_nc_net_pct_156w@13874A"`. Use the alias in filters, trigger or reference, never in `[exit]` |
| `[exit]` | see below; needed only by `alpha setup trade` |
| `[study]` | `horizons = [1, 5, 10]`, `primary = 5` (one of the horizons); needed only by `alpha setup study` |
| `idea_card` | `idea_card = "my-idea"` at the top, before any table. Links an [idea card](idea-card.md) |

**The `[exit]` section** Keys: `direction`, `stop`, `target`, `opposite`, `time_bars`. All are optional.
- `direction = "short"` (default `"long"`).
- `stop = "5 %"` is a percent distance. `stop = "2 atr(14)"` is an ATR distance. A price expression such as `"lowest(low, 5)"` or a
  `[reference]` name is a level. `target` takes the same forms.
- `opposite = "close < sma(close, 50)"` exits at the next open when it becomes true.
- `time_bars = 20` exits at the close of the last held bar (default 250). Exits use price data only.

**Words you can use** Sources: `open high low close volume`. Functions: `prev sma ema atr highest lowest pct_change abs crosses_above
crosses_below for_bars within_bars`. Also `+ - * /`, comparisons, `and`, `or`, `not`.

**What it cannot tell you** Whether the setup works. A valid file only means the program can read it.
