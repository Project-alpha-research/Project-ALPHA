---
owner: research pipeline
sources:
  - apps/alpha-cli/src/alpha_cli/setup_cmds.py
  - apps/alpha-cli/src/alpha_cli/spine/setup_find.py
  - apps/alpha-cli/src/alpha_cli/spine/contact_sheet.py
verified: b6a551af2f543465
---
# Setup find

**Reach for it when** the owner describes a chart setup ("a double bottom", "a pullback in an
uptrend") and wants to see every past match before any rule is fixed.

**Commands**
```text
alpha setup new <name> --asset SPY --when "<condition>" --horizon 10 --stop "5 %"  # writes <data folder>/specs/<name>.toml; options left out keep defaults
alpha setup find --when "<condition>"     # no file: same options; also on study and trade
alpha setup find <spec.toml> --asset SPY --context-bars 60 --json
```
**See stored results:** Workstation → Research → Setup Lab.
**How to read it**

- The spec is a TOML file: every section and key is in [setup spec](setup-spec.md). Expressions read only past bars
  ([setup causality](../../docs/reference/invariants/study.md#setup-causality)).
- Lead with separate occurrences, not matching days: days within ten bars of each other are one
  occurrence (`accepted_clusters` against `accepted` in `totals`).
- `sheets` lists contact sheets: accepted matches (the first day of each occurrence), and one greyed sheet
  of rejected samples with the reason in each panel title. Every panel stops at the entry open.
- Bars from 2024-01-01 on are held back (`reserved-period-held-back`). Context is 60 bars. Repeats redraw nothing; `outcomes-viewed` replaces
  `outcomes-not-viewed` when a sibling study or trade manifest exists.

The find uses the worst [data health](data-health.md) verdict. A failed one stops it unless `--accept-bad-data` has a reason.
**What it cannot tell you**

- Nothing about what happened after entry: no return, exit or control is computed. A match count is not
  evidence of an edge. Use [setup study](setup-study.md) for a counted look at outcomes and controls.
- Daily bars only; the evaluator records the day a pattern became known, not the dates of its own lows.

**Next** Show the owner the sheets and ask whether the matches look like the setup they meant; adjust the
spec before anything is tested.
