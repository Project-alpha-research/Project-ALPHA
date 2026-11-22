---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/options_cmds.py
  - packages/alpha-data/src/alpha_data/options/derived.py
verified: 041b146abe048deb
---

# Options derived series

**Reach for it when** you want to know how expensive options on a stock are, as context for an idea: is volatility
high or low for this name, are puts richer than calls, is the term upward or downward.

**Command**

```text
alpha options derived AAA --series iv30 --series skew_25d --rows 20 --json
```

**How to read it**

- `iv30`: at-the-money implied volatility for a constant 30 days ahead, as a yearly rate (0.20 is 20%).
- IV rank and IV percentile: where today's `iv30` sits in the last 252 sessions. They are null for the first 251 sessions.
- `skew_25d`: 25-delta put volatility minus 25-delta call volatility at 30 days. Above 0: puts cost more.
- `term_slope`: volatility at about 90 days minus `iv30`. Above 0: longer options cost more.
- `iv_minus_rv`: `iv30` minus realized volatility (21 daily log returns from the stored bars, as a yearly rate).
- Each series ends with a coverage line: sessions with a value and the count of nulls by reason.
- Each row has `known_from`: the first instant the value was knowable. A null shows its reason, never zero.

**What it cannot tell you**

- Direction or a trade. These are readings, not signals or advice.
- Real market levels today: only the synthetic fixture is stored until the owner adds a data package.
- The store records no rate or dividend. The command assumes 0 unless you pass `--rate` or `--dividend-yield`.

**Next** Join the series to an idea as context once the context store carries it; until then quote the command and dates.
