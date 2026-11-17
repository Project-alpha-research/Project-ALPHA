---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/setup_cmds.py
  - apps/alpha-cli/src/alpha_cli/spine/setup_find.py
  - apps/alpha-cli/src/alpha_cli/spine/contact_sheet.py
verified: b656334df3e53521
---

# Setup find

**Reach for it when** the owner describes a chart setup ("a double bottom", "a pullback in an
uptrend") and wants to see every past match before any rule is fixed.

**Commands**

```text
uv run alpha setup find <spec.toml> --json
uv run alpha setup find <spec.toml> --asset SPY --context-bars 60
```

**How to read it**

- The spec (TOML) has a setup table (name, idea, assets, timeframe "1D", event), ordered filters, an optional
  trigger (when, within) and reference levels; expressions read only past bars
  ([setup causality](../../docs/reference/invariants/study.md#setup-causality)).
- Lead with separate occurrences, not matching days: days within ten bars of each other are one
  occurrence (`accepted_clusters` against `accepted` in `totals`).
- `sheets` lists contact sheets: accepted matches (the first day of each occurrence), and one greyed sheet
  of rejected samples with the reason in each panel title. Every panel stops at the entry open.
- A second run on the same spec and data adds the label `repeat` and redraws nothing.

**What it cannot tell you**

- Nothing about what happened after entry: no return, exit or control is computed. A match count is not
  evidence of an edge. Outcomes, the event study and random-date controls are not available yet.
- Daily bars only; the evaluator records the day a pattern became known, not the dates of its own lows.

**Next** Show the owner the sheets and ask whether the matches look like the setup they meant; adjust the
spec before anything is tested.
