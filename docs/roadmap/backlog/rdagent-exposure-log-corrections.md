# Exposure log: correct entries and match ideas by economic family

**Status:** Idea
**Rough size:** M

## Problem / why

The exposure log (pull request #178) is append-only and labels trials by a name pattern.
The first real use showed two gaps:

- **Patterns over-match.**
  - The volatility entry's pattern `vol` also matches `volume`, so `volume_trend_28d_90d` was
    labelled as volatility-family.
  - `momentum_7d` (cross-sectional) matched the XRP own-trend study, because XRP is one of the
    15 coins.
  - Labelling errs toward "exposed", which is the safe direction, but the label then says
    little.
- **No correction path.** A wrong entry cannot be corrected or retired without editing the
  append-only file.

## What "done" looks like

- A `supersedes` field: a new entry can replace or retire an earlier one. Readers use the latest
  entry in the chain and keep the history.
- Each trial carries an economic `family_id`, assigned when it is judged. The assignment comes
  from a small fixed vocabulary, picked by ALPHA from the factor's hypothesis text with a stated
  rule, or by a person, and recorded. Exposure matching then uses the family id, not the name.
- `exposure list` shows which trials changed label after a correction.

## Dependencies

Pull request #178.

## Sources

- The swing loop of 2026-11-15 (run `rdloop-swing-deepseek-20261115-1`), with labels from
  `exposure list`.
