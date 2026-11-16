# Rule language: session, time of day, open and volume

**Status:** Idea
**Rough size:** M

## Problem / why

Found on 2026-11-15 while running intraday system tests. The owner's rule language (`alpha rules`)
cannot express an opening-range breakout or any idea that depends on the session clock: a rule's
sources are only `high`, `low` and `close` (no `open`, no `volume`), there is no time of day,
session open, "first N bars of the session", session high/low so far, or day-of-week, and no
"crosses" (rules are stateless conjunctions on the decision bar). Intraday bars now work end to
end, so these are the main missing pieces for intraday swing-entry ideas.

## What "done" looks like

- Sources `open` and `volume`.
- Session-aware sources computed point-in-time from bars already closed: minutes since the session
  open, bar index within the session, the opening range (high/low of the first N minutes) once it
  has closed, session high/low so far.
- Optional cross conditions (state across two consecutive decision bars).
- Each new source has a future-poison bias guard with a leaky twin.
- Operands for a new high over a long window (a 52-week-high breakout) and for strength relative
  to a benchmark, so the common momentum styles (own-history, cross-sectional top and bottom
  slices, sector-neutral, breakout, volume-confirmed) can all be written as rules.

## Dependencies

None.
