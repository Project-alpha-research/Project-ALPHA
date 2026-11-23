---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/spine/setup_context.py
  - packages/alpha-study/src/alpha_study/setup/context.py
  - packages/alpha-data/src/alpha_data/context/attach.py
verified: 346d6900dd873041
---
# Setup with a context condition

**Reach for it when** the owner asks "what happened after positioning (or short volume) was extreme?" and a
[setup find](setup-find.md) should use that series as a condition.
**Spec** (full example: `research/examples/setup-context.example.toml`)
```toml
[context]
es_pos = "cot_nc_net_pct_156w@13874A"   # alias = "series@key"; the key is declared, SELF = the asset's symbol
[filters]
very_long = "es_pos > 0.9"
```
```text
alpha setup new pos --context "es_pos=cot_nc_net_pct_156w@13874A" --when "es_pos > 0.9"   # writes the spec
alpha setup find <spec.toml> --json
alpha setup study <find_id> --json
```
`--context "alias=series@key"` also works on `find`, `study` and `trade`; repeat it for more series.

**How to read it**
- Series and keys: [positioning and short volume](positioning-short-volume-context.md). Aliases work in `event`, `filters`, `trigger`
  and `reference`, not in `[exit]`.
- Each asset prints the span where the series has a value, the days the condition was true and its **separate spells**. A weekly value
  repeats on daily bars, so days overstate the sample: lead with spells and occurrences.
- `context` in the JSON lists bars with no value by reason: `not-yet-known`, `stale`, cot-delayed-release-unverified, `series-warm-up`.
  A stale value rejects the event as context-stale. A null is never a match.
- Label `short-context-history`: under 3 years of condition data. Read it as a hint, say so.
- Study and trade add the same sentence. Random controls start and end where the condition data has a value on that asset.

**What it cannot tell you**
- Cause. A reading is not a verdict and promises no profit. Different levels or series are new tests, counted in the same idea family.
- Data after 2023-12-31 is held back; rows added later change nothing. Short volume covers FINRA facilities only.
**Next** Report the occurrences and spells first, then the study reading. Say "Hypothesis:" for any reason you give.
