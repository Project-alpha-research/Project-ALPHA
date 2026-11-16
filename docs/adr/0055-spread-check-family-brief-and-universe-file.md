# ADR-0055: The factor judge checks the top-minus-bottom-third spread before the replay; the proposer sees idea families; the universe is a file; model calls have a time limit

**Status:** Accepted
**Date:** 2026-11-16
**Deciders:** the orchestrating AI agent, under the owner's delegation of these decisions
(recorded in [owner decisions, volume 3](../reference/project/owner-decisions-3.md)); built and
reviewed by AI agents
**Amends:** [ADR-0049](0049-alpha-judges-rdagent-factors.md) points 2, 6 and 8;
[ADR-0050](0050-swing-clocks-in-the-factor-judge.md) points 3, 5 and 6

## Context

The 2026-11-16 health check of RD-Agent's factor loop (pull request #212) found:

1. Since the swing judge (ADR-0050), 18 factor × clock trials passed the rank screen and were
   replayed; 15 of them lost money **before costs** when ALPHA held the top third. On 15 coins a
   factor can rank the coins well on most days and still hold the losing third on average (a few
   volatile coins dominate the mean). The proposer was told only "failed the replay".
2. The universe (15 Binance coins), the calendar and the 365-day year were constants.
3. Every run had model calls that reasoned for 8-12 minutes and returned no text
   (`invalid_provider_response`); one ended a run. The gateway waited up to 900 s per read.
4. The proposer's ledger summary showed 24 of 70 factors, not grouped by idea, and memory kept
   refining one idea (9 near-variants of "price near its 52-week high", none passed).
5. Free local embedding look-ups count toward the 60-call cap (20-23 of 60 per run).

## Decision

1. **Spread check, before the replay, never instead of it.** For every clock that passes the rank
   screen (BH q < 0.10), the evaluator first computes, on the screen's own non-overlapping decision
   days, the mean forward return of the top third minus the bottom third, ranked in the factor's
   claimed direction at the decision day's close, returns from the next open to the open h days
   later, before costs (`rdagent_factor_eval.spread`). The thirds are the replay's own selection
   (k = round(n/3), ties by instrument name). The clock passes only if the mean spread is positive
   **and** stays positive when ties are broken in the reverse name order. Otherwise the clock is
   `SPREAD_FAIL` with reason `top-third-does-not-beat-bottom-third` and its numbers, and it is not
   replayed. A held name with no forward return fails loud (it is never dropped). Reported: mean
   spread per hold and per year, top-third and bottom-third mean returns, decision days, a
   t-statistic with the autocorrelation-adjusted effective sample size and a seeded
   stationary-bootstrap interval (the screen's own estimators from `alpha_validation`, reused; no
   new estimator), the share of the top third replaced per rebalance and the cost that implies.
   The spread is computed and recorded for every screened clock so the proposer can see it; only
   the q-passing clocks are gated by it. The replay and the candidate rule are unchanged: a
   candidate still needs a swing clock with q < 0.10, a positive spread **and** positive net excess
   in the replay. This is a stricter judge and a cheaper failure; it adds no way to pass.
2. **The proposer is told the truth in detail** (ALPHA's brief layer only; RD-Agent's source is not
   edited, ADR-0051). Each ledger line gives, for every clock that reached the spread check, the
   top- and bottom-third returns, the yearly spread before costs, its t-statistic, the share of the
   top third replaced per rebalance and the cost that implies, then the replay's before- and
   after-cost returns where it ran. Above the lines, a summary groups **every** distinct factor by
   idea family (a deterministic name-keyword table, `alpha_factor_judge.FAMILY_KEYWORDS`): tries,
   best result and how each failed. Families with N or more tries and no candidate are named, and
   the proposer is told not to propose another near-variant of them and to move to a different
   family. N is `--family-switch-after` (default 3).
3. **Universe, calendar and year length are a file** (`AlphaRdagentUniverseV1`,
   `alpha_cli._rdagent_universe`; examples in `workers/rdagent/universes/`). A file names the
   source, the instruments (`all-in-store` or a list), an optional point-in-time liquidity rule,
   the calendar and the minimum universe. The calendar fixes the year length and the three clocks
   (calendar days: 365, 1/7/28; exchange sessions: 252, 1/5/20), so a universe file cannot choose
   its own clocks. The liquidity rule keeps, on each decision day d, names whose last
   `lookback_days` daily bars up to and including d all exist and whose median quote volume is at
   least the threshold, at most `max_names` of them by that median; a name outside it has no rank
   that day. It reads no bar after d. Runs frozen without a file use the built-in default, which is
   the earlier behaviour.
   - **Crypto:** the local Binance store holds exactly 15 coins, so nothing can be widened without
     a data pull. `binance-spot-liquid.json` applies the rule (90 days, median ≥ USD 1 million,
     at most 50 names); it keeps all 15 coins on every exploration day. The survivorship bias is
     unchanged and disclosed: the 15 are 2026 survivors.
   - **US stocks:** the Alpaca store holds 15 symbols, of which 9 are single stocks (AAPL, AMZN,
     GOOGL, JNJ, JPM, META, MSFT, NVDA, XOM) and 6 are funds; thirds of 9 names are 3 names each.
     `alpaca-us-stocks.json` is wired and is refused by `freeze` ("has 9 of its names; ...
     need at least 15"). The exchange-session calendar is configured but not yet evaluable: the
     clocks, panel checks and replay assume consecutive calendar days.
4. **Per-call time limit.** On the paid route each model call has a total limit (`--api-timeout`,
   default 180 s) enforced by a deadline on the whole call, not only on each socket read. A call
   that exceeds it ends as `provider_timeout`; it and an empty or invalid reply are retried
   `--provider-retries` times (default 1, at most 3). Every attempt is reserved against the run
   and monthly call and dollar caps like any other, and an abandoned attempt's reservation stays
   charged.
5. **Caps unchanged.** What counts toward the 60-call, USD 10 per run and USD 50 per month caps,
   and their values, are unchanged. The run receipt gains `call_split`: model chat requests,
   attempts and dollars versus free local embedding requests and attempts, provider timeouts,
   empty replies and retried attempts. Whether embeddings should count is left to the owner.

## Options considered

| Option | Verdict |
|---|---|
| Replace the rank screen by the spread | Rejected: removes an existing gate; the decision is to add, never loosen |
| Require a significant spread (t > 2) | Not now: with 39 monthly decision days only large effects are detectable; the sign rule plus the unchanged screen and replay is the stated minimum; the t-statistic is reported |
| Drop a held name with no forward return | Rejected: keeps only survivors of the holding period (look-ahead); fail loud instead |
| Let a universe file choose clocks or year length freely | Rejected: a new way to search clocks; the calendar fixes both |
| A per-read socket timeout only | Rejected: a provider that keeps the connection alive while it reasons never trips it |
| Exclude embeddings from the call cap | Not decided here: left to the owner; the receipt shows the split |

## Consequences

- Re-judging the ledger offline: the spread check rejects 16 of the 18 replayed factor × clock
  trials before the replay (all 15 that lost before costs and one daily `FAST_ONLY` whose top
  third beat the basket but not the bottom third). Neither of the two that pass it is a swing
  clock.
- Ledger rows from this change may carry `SPREAD_FAIL` (overall and per clock) and a `spread`
  object per screened clock; earlier rows stay valid.
- A repeat copies the first trial's spread.
- Not covered: a survivorship-free or wider crypto universe (needs delisted and more coins in the
  store, and a replay that handles listings and delistings); a stock universe (needs a data pull of
  at least about 100 liquid single stocks with point-in-time membership, and the session calendar
  in clocks and replay).

## Implementation anchors

- `apps/alpha-cli/src/alpha_cli/rdagent_factor_eval.py`: `spread`, `spread_at_clock`, `_thirds`,
  the gate in `_replay_clocks`, `freeze(..., universe)`, `_alpaca_viability`.
- `apps/alpha-cli/src/alpha_cli/_rdagent_clocks.py`: `overall_status`, `spread_note`.
- `apps/alpha-cli/src/alpha_cli/_rdagent_universe.py`: `validate`, `eligibility`, `evaluable`.
- `workers/rdagent/alpha_factor_judge.py`: `FAMILY_KEYWORDS`, `idea_family`, `family_summary`,
  `spread_line`.
- `workers/rdagent/model_gateway.py`: `post_json` deadline, `PROVIDER_RETRYABLE`, `Gateway.chat`.
- `workers/rdagent/factor_loop_launch.py`: `call_split`, the new options.
- Tests: `tests/unit/test_rdagent_factor_spread.py`,
  `tests/bias_guards/test_rdagent_spread_future_poison.py`, and the new cases in
  `test_rdagent_factor_judge.py`, `test_rdagent_model_gateway.py`, `test_rdagent_factor_launch.py`.
