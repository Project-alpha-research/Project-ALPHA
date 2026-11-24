---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/context_free_cmds.py
  - packages/alpha-data/src/alpha_data/context/cftc_cot.py
  - packages/alpha-data/src/alpha_data/context/finra_short.py
  - packages/alpha-data/src/alpha_data/context/attach.py
  - apps/alpha-cli/src/alpha_cli/context_derived_cmds.py
verified: 97c7fd6d45e706d1
---

# Positioning and short-volume context

**Reach for it when** you ask who was positioned and how heavily a stock was sold short: weekly futures positioning
and daily short sale volume. Descriptive inputs only; no signal is defined on them.

**Commands** (no key; the owner pulls once, you read)

```text
alpha context list --json
alpha context show-cftc-cot --market 13874A --as-of 2024-03-15T21:00 --json
alpha context show-finra-short-volume --symbol SPY --as-of 2024-03-15 --json
alpha context show-derived --series cot_nc_net_pct_156w --key 13874A --asset SPY
```

**How to read it**

- `list` shows stored tables under `free_context`. Nothing stored: the owner runs `pull-cftc-cot` or `pull-finra-short-volume`.
- A row appears only once public. COT describes Tuesday and is known from Friday 15:30 US Eastern (or the stamp, if later; later in holiday
  weeks). FINRA volume for a day is known from 12:00 UTC the next calendar day. Always pass `--as-of`.
- `show-derived`: a [derived series](../../docs/reference/invariants/data-context.md#derived-series-and-the-one-join) on daily bars.

**What it cannot tell you**

- FINRA files cover trades reported to FINRA facilities only, not all exchange volume: the level understates total
  volume. Compare a symbol with itself over time, never with exchange totals.
- Cause or direction. Short volume is not short interest; positioning is not intent. Say "Hypothesis:".
- Only `show-derived` and a [setup find](setup-context.md) read these on bars (cut 2023-12-31); no rule test or RD-Agent does. Count spells.

**Next** Ask "what happened after this was extreme?" with a [setup find](setup-context.md); a rule test cannot use them yet.
