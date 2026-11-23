---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/lookalike_cmds.py
  - apps/alpha-cli/src/alpha_cli/follow_lookalike.py
---
# Lookalike and unusual

**Reach for it when** the owner asks "has the chart looked like this before?" or "is this stretch strange?".

**Commands**
```text
alpha lookalike --asset SPY --last 30 --json
alpha lookalike --asset SPY --last 60 --top 10 --horizons 5,10,20
alpha lookalike --asset SPY --last 30 --today   # forward use: the newest bars against older history
alpha unusual --asset SPY --window 30 --json
```
`--last` is the number of latest bars to match (at least 5, default 30). `--top` caps the matches (default 10).
`--horizons` sets the bars after each match to report. `--max-distance` replaces the default closeness limit.

**How to read it**
- A lookalike is an earlier stretch with the same shape. The default limit is a shape correlation of 0.80.
- Each match lists what followed it at each horizon. Read the spread of those outcomes, not one match.
- Matches never overlap each other, but what followed them can share bars, so they are not independent. Few matches mean a thin reading.
- `unusual` says how unlike every earlier stretch the latest bars are. It says nothing about up or down.
- Bars from 2024-01-01 on are held back. Each `lookalike` run adds one exploratory trial to the ledger.
- `--today` is forward use: "a look at today, not a test". It compares the newest bars with history before 2024-01-01 only.
  It writes no run and counts no try. Its "what followed" never reaches past that history.
- Stored daily bars by default. Use `--timeframe` for another stored bar size.

**What it cannot tell you**
- It is descriptive, not a forecast. Past matches do not make the next bars follow them.
- Shape ignores volume, news and the market around it. A match is not an edge.

**Next** Show the owner the matches. For a rule that could be tested, write an [idea card](idea-card.md) and use the [rule test](rule-test.md).
