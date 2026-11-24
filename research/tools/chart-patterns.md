---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/chart_cmds.py
  - apps/alpha-cli/src/alpha_cli/chart_pattern_picture.py
  - apps/alpha-cli/src/alpha_cli/pattern_events.py
  - apps/alpha-cli/src/alpha_cli/spine/pattern_context.py
verified: 1c4d645032d0a671
---
# Chart patterns: see one, then test one

**Reach for it when** the owner asks "show me the trend lines on NVDA" or "every time a rising trend line broke, what came next?".

**See it**
```text
alpha chart overlays NVDA -p trendlines [--since 2024-01-01] [--end 2025-06-30]
```
It writes a plain and an annotated picture and prints 3 lines: how many, the most recent and its date, the paths.
A window that ends after 2023-12-31 adds a note that the held-back period is inside it.
Swings and other markers are all drawn; lines and outlines show the 5 most recent that do not crowd, numbered in the legend.
The default window is the last two years. Families: swings, dc_extremes, structure_levels, trendlines, flags,
head_shoulders, wedges, triple_taps, harmonics. Drawn only, no events: pips, market_profile, levels.

**Test it** Use the event as a [setup find](setup-find.md) condition: `alias = "series@SELF"` under `[context]`
([setup context](setup-context.md)). Examples: `research/examples/setup-trendline-break.example.toml`,
`research/examples/setup-pivot-reversal.example.toml`.
Series: swing_/dc_/structure_ + high or low, falling_/rising_line_break, bull_/bear_ + flag or pennant, hs_top, hs_bottom,
wedge_ + falling, rising or symmetrical, triple_tap, harmonic_bull, harmonic_bear.
`alpha setup find <spec.toml> --json`, then `alpha setup study <find_id> --json`.

**How to read it**
- An event is 1 on the bar where it became known, else 0. A swing is known only after its confirmation bars, so the event sits on
  that later bar, never on the pivot.
- The first 60 bars have no value (`series-warm-up`). A missing value never matches.
- Head and shoulders and wedges are re-run on the bars up to each day, so a later bar never changes an earlier event.

**It cannot tell you**
- Cause. A pattern is a reading about the past, not a forecast. Random prices show many: [random-price null](random-price-null.md).

**Next** Report the event count first, then the study reading.
