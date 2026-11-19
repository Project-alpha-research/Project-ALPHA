---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/context_free_cmds.py
  - packages/alpha-data/src/alpha_data/context/cftc_cot.py
  - packages/alpha-data/src/alpha_data/context/finra_short.py
verified: 35e2291550db627d
---

# Positioning and short-volume context

**Reach for it when** a question is "who was positioned, and how heavily was the stock sold short?": weekly futures
positioning (large speculators, commercials) and daily short sale volume. Inputs only; no signal is defined on them.

**Commands** (no key; the owner pulls once, you read)

```text
uv run alpha context list --json
uv run alpha context show-cftc-cot --market 13874A --as-of 2024-03-15T21:00 --json
uv run alpha context show-finra-short-volume --symbol SPY --as-of 2024-03-15 --json
```

**How to read it**

- `list` shows stored tables under `free_context`: first and last period, last `known_from`, caveat.
- A row appears only once public. COT describes Tuesday and is known from Friday 15:30 US Eastern (or the stamp, if later; later in holiday
  weeks). FINRA volume for a day is known from 12:00 UTC the next calendar day. Always pass `--as-of`.
- Nothing stored: the owner runs `alpha context pull-cftc-cot --market <code>` or `pull-finra-short-volume --symbol <T>
  --start <date> --end <date>`.

**What it cannot tell you**

- FINRA files cover trades reported to FINRA facilities only, not all exchange volume: the level understates total
  volume. Compare a symbol with itself over time, never with exchange totals.
- Cause or direction. Short volume is not short interest; positioning is not intent. Say "Hypothesis:".
- No research command reads these series yet; a research read must cut at `--as-of` and refuse the reserved period.

**Next** Put the question to the [rule test](rule-test.md) with a defined rule; none exists on these series yet.
