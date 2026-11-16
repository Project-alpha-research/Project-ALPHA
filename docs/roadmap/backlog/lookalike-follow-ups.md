# Lookalikes and novelty: what comes after the first commands

**Status:** Idea
**Rough size:** M

## Problem / why

Pull request 211 adds `alpha lookalike` (earlier stretches shaped like the latest bars, and
what followed) and `alpha unusual` (how unlike all earlier history the latest bars are), using
STUMPY. A private study (2026-11-16) planned more, and found limits, that the pull request does
not carry:

- A first demonstration on SPY found 21 lookalikes of a hand-picked month and no edge against
  random dates: the tool kills a chart idea in seconds. Lookalikes are pictures for deciding
  what to test, never evidence (no random-date comparison by default, no costs).
- Honesty rules still to enforce: the random-date comparison always shown; "known on the day"
  and "hindsight" labels kept apart; shape, not size, is compared; matches at least a window
  apart; every run a counted exploratory trial.
- Later uses: a nightly novelty score per market as a warning that a backtest faces unseen
  conditions; repeated shapes and odd-ones-out over the whole history as idea seeds for
  RD-Agent, labelled hindsight; one example searched across every stored symbol.
- Limits: equal-length windows only; flat stretches give noisy matches; intraday is untested;
  one maintainer; the first call compiles (about half a minute); the hourly SPY store holds only
  about three months; the shared chart code draws the year label mid-year.
- The compiler STUMPY needs adds about 190 MB; installing it in the main install or as an
  optional extra is the owner's choice.
- If shapes need to stretch in time, dtaidistance is the later option (register).

## Where it would live

`packages/alpha-patterns` (adapter), `alpha lookalike` and `alpha unusual`, the Setup Lab screen.

## What "done" looks like

Each point is a rule in the patterns invariants, a checklist row, or dropped by the owner.

## Dependencies

Pull request 211.

## Sources

- [Checklist stage 3](../production-scope.md#3-look-before-testing)
