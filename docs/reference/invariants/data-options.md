---
owner: data layer
sources:
  - packages/alpha-data/src/alpha_data/options/**
  - tests/unit/test_options_schema.py
  - tests/unit/test_options_store.py
  - tests/unit/test_options_held_back.py
  - tests/unit/test_options_forward_guard.py
  - tests/unit/test_options_pricing.py
  - tests/unit/test_options_implied.py
  - tests/unit/test_options_priced_fixture.py
  - tests/unit/test_options_conventions.py
  - tests/unit/test_options_american.py
  - tests/unit/test_options_american_implied.py
  - tests/unit/test_options_derived.py
verified: 2f74fb28e9f0f764
---

# Data layer invariants: options

Rules for `alpha_data.options`: the provider-neutral option chain records, their store, the synthetic fixture adapter and the
implied-volatility and greeks solver. No provider code and no network live here. The rest of the data layer is in [data.md](data.md).
The component page is [options data](../project/components/options-data.md).

## Records

All records are frozen dataclasses that check themselves on construction. A bad value raises `OptionsDataError`
(a `DataError`) and its `field` attribute names the field.

- `ContractId`: underlying id, root, expiry, strike (exact `Decimal`), right `C` or `P`, style `A` or `E`, multiplier,
  `listed_on` (or `None` when unknown) and `provider_symbol`. The identity `key` ignores `provider_symbol`, which is provenance only.
- `Quote` (bid, ask, sizes, `quote_ts`) and `Trade` (last, `last_ts`, volume) are separate records. A quote is never
  filled from a trade.
- `Greeks` carries `source` (`provided` or `computed`) and `model`. A chain row has two slots, `provided` and `computed`;
  a block in the wrong slot is refused. They are never mixed in one column.
- `ChainSnapshot`: contracts with quotes at ONE `snapshot_ts`, known from `known_at`.

## Invalid data fails loud

Errors (typed, naming the field): non-finite or negative prices, strike at or below zero, unknown right or style,
non-positive multiplier, naive or non-UTC datetimes, `known_at` before `snapshot_ts`, a duplicate contract in one snapshot,
a contract on another underlying, an expiry before the snapshot day, a `listed_on` after the snapshot day, a quote, trade or open-interest date
stamped after `known_at`, a snapshot written older than the newest stored one, a non-finite or negative provider IV.

Labels, not errors (`quote_labels`, `Greeks.labels`): `crossed` (bid above ask), `zero_width` (bid equals ask) and
`iv_sentinel` (a provider IV of exactly zero). Vendors publish such rows; the label lets a reader decide.
The 2026-11-19 design is silent on this; the choice is an open reading.

## Point-in-time store

- Layout: `<data_dir>/options/<provider>/<underlying_id>/<yyyy>/<yyyymmddThhmmssZ>.parquet` plus a `.json` sidecar with
  `sha256`, `rows`, `snapshot_ts`, `known_at`, `fetched_at`, `adapter_version` and `schema_version`.
  The design names `<date>.parquet`; a timestamp name allows more than one snapshot a day. Open reading.
- One flat Parquet row per contract; the snapshot fields repeat on each row. Strikes are stored as exact decimal text.
- Snapshots are append-only. The same content again is a no-op. Different content for an existing snapshot is refused.
  A read checks the hash, the row count and the schema, and rebuilds every record, so a damaged file fails loud.
- The `known_at` filter uses the sidecars, so a future snapshot's Parquet file is never opened by an earlier read.
- A read cut-off must be timezone-aware. Names in paths (provider, underlying) allow only ASCII letters, digits, `_`, `.`, `-`,
  must start with a letter or digit and may not contain `..`; anything else is refused, so a path cannot leave the store folder.
- Read checks: the hash, the row count, the schema and the times in the sidecar must all match the Parquet file.
  A tampered Parquet or sidecar fails loud with the file name.
- Row labels (`ChainRow.labels`: `crossed`, `zero_width`, `iv_sentinel`) are computed from the stored row, so they come
  back with every read result.

## Research reads and forward use

The held-back period (`alpha_core.reserve.RESERVED_DAY`, no date literal here) works as in the bars store.
- Research reads cut. `snapshots_as_of` and `chain_as_of` take the caller's `as_of`, cap it at the last instant before the
  held-back day, and return only snapshots with `known_at` at or before that time. The result (`SnapshotsRead`, `ChainRead`)
  carries `held_back`: how many snapshots known by `as_of` the cap hid. A caller must disclose it. No quote, trade, greek or
  open-interest date from the held-back period is returned. A contract that expires after the boundary stays: it was listed
  and known before it. The expiry filter uses the capped day.
- Forward use reads the newest data on purpose. `forward_chain_as_of` returns the newest snapshot known at `as_of` with no cap.
  Use it only to follow an idea on paper, for the "active today" view or to show market data. Its name is deliberate.
- Guard: `tests/unit/test_options_forward_guard.py` fails if any source file other than the store names
  `forward_chain_as_of`. A forward-use home must be added to its list with a reason. Research-side code (spine, toolbox,
  Setup Lab, RD-Agent modules, the hypothesis scan) is therefore kept off it.
- Size: the fixture measures about 227 bytes per row for 54-row files and about 17 for a 1,920-row chain. The design estimate
  is about 35 bytes per row. Real chains compress less well than synthetic ones, so recheck with the provider's data.

## Pricing and implied volatility

Pure-math modules, no data reads and no clock: `pricing.py` (closed-form models and greeks), `tree.py` and `tree_greeks.py`
(American tree), `iv_core.py` (day count, result types, root finder), `implied.py` (mid, closed-form solver, `solve_row`) and
`implied_american.py` (American solver). They live inside `alpha_data.options` so the solver can fill the row's `computed`
slot. The sources are in the module docstrings.

- Models: Black-Scholes-Merton (Black and Scholes 1973, the call formula; Merton 1973) for a spot with a continuous dividend yield, and
  Black-76 (Black 1976) for a forward. European exercise only here (American: next section). One constant volatility, constant rate and yield.
- Inputs are explicit: spot or forward, strike, years, rate and dividend yield (None for a forward). There is no default for
  the rate or the yield. The stored model name records which were used. Its format is stable and parseable:
  `<model>;r=<rate>;q=<yield or forward>;day_count=act365f;theta=per_calendar_day;vega=per_1.00_vol`. Split on `;`, then on
  the first `=`. The numbers are shortest round-trip float text. The `Greeks` schema is not changed, so stored hashes stay.
- Day count: ACT/365 fixed on calendar time. `years_between(snapshot_ts, expiry_ts)` takes two aware-UTC datetimes. The caller
  passes the exchange's expiry cut-off for the series in UTC (`expiry_time_utc`); the contract only has a date. A naive or
  non-UTC datetime is an error naming the field. An expiry before the snapshot is an error; an equal one is the typed
  outcome `zero_time_to_expiry`.
- Conventions: `vega` per 1.00 of volatility (divide by 100 for one point); `theta` per calendar day (times 365 for a year);
  `rho` per 1.00 of the rate. `delta` and `gamma` are with respect to the input underlying. Quotes are per share; the
  multiplier does not scale them. `rho` is in `ModelGreeks` only: the stored `Greeks` block has no rho field. Every
  `ModelGreeks` and `IvSolved` carries a `conventions` record with these units.
- Converting a provider's greeks before any comparison: theta per trading day = ALPHA theta * 365 / 252 (for a 252-day
  provider); vega per vol point = ALPHA vega / 100; rho per 1% = ALPHA rho / 100. Never compare unconverted numbers.
- Edges: pricing needs years > 0 and vol > 0, and vol * sqrt(years) must not be zero in floating point (a named error).
  As vol or time falls to zero the price tends to the discounted intrinsic on the forward, max(phi D (F - K), 0).
## Mid price and implied-volatility solver

- Mid price: `mid_price(quote)` is (bid + ask) / 2. A crossed, zero-width or zero-bid quote has no mid and returns its label
  (`crossed`, `zero_width`, `zero_bid`). A zero bid is never averaged; `solve_row` returns `no_mid` for it.
- Solver: safeguarded Newton with a bracket (bisection fallback) on volatility in [0.0001, 10.0]. A true volatility outside
  that interval is the typed outcome `implied_vol_outside_search_interval`, never a clamped number. The price is strictly
  increasing in volatility (vega > 0), so the root is unique.
- No-arbitrage bounds, with D = exp(-rT) and F the forward (F = S exp((r - q) T) for a spot): call max(D (F - K), 0) < C < D F,
  put max(D (K - F), 0) < P < D K. For a spot, D F = S exp(-qT). The inequalities are strict with no tolerance, so a price at
  or below intrinsic is always `price_outside_no_arbitrage_bounds`. A price a hair above intrinsic solves to a tiny
  volatility with very low vega, so it is labelled `low_vega` and not stored.
- Typed outcomes, never a silent NaN: `IvSolved` or `IvUnsolved` with a reason. Reasons: `price_outside_no_arbitrage_bounds`,
  `zero_time_to_expiry`, `american_style_needs_tree_inputs`, `implied_vol_outside_search_interval`, `did_not_converge`, `no_quote`
  and `no_mid`. A non-finite input raises `OptionsDataError` naming the field.
- Low confidence, exact rule: `iv_uncertainty = price_resolution / vega` at the solved volatility (vega per 1.00). The result
  is `low_vega` when `iv_uncertainty > 0.005` (half a vol point). With the default resolution of half a cent that is vega < 1.0.
- Computed block: `solve_row` fills only the `computed` slot (source `computed`, delta, gamma, vega, theta, iv) and only for a
  normal-confidence solve. The provided slot is never touched. A low-confidence or unsolved row comes back unchanged.
- American style: `solve_implied_vol(style="A")` returns `american_style_needs_tree_inputs`; use `solve_row` or
  `solve_american_implied_vol` (next section).

Known-answer tests: Hull's published prices and greeks, Haug's Black-76 value, put-call parity to 1e-10, every greek against a
central finite difference, the conventions record, the model-tag format, no mid for a zero bid, round trip of price to
volatility (error 1.6e-14 where confidence is normal), the zero and large
volatility limits, monotonicity, and Black-76 equal to BSM when the forward is built from the same inputs.

## American style: CRR tree

`tree.py`, `tree_greeks.py`, `implied_american.py`. Sources: Cox, Ross and Rubinstein (1979), Journal of Financial Economics 7(3);
the escrowed-dividend treatment for known cash dividends as in Hull, "Options, Futures, and Other Derivatives" (binomial-tree chapter);
Haug, Haug and Lewis (2003, Wilmott) on its weakness. Cross-check: QuantLib 1.44 escrowed finite differences, a few 1e-4 at 2000 steps.

- Tree: u = exp(vol sqrt(dt)), d = 1/u, p = (exp((r - q) dt) - d) / (u - d); the node value is max(exercise, discounted
  expectation) at every node. Price = average of the N and N + 1 step trees; default 500 steps. A step with
  d < exp((r - q) dt) < u false (vol < |r - q| sqrt(dt)) returns `TreeRefused`, never a number.
- Inputs are explicit: spot, strike, valuation and expiry instants (aware UTC, ACT/365 fixed), rate, continuous yield, a tuple of
  `Dividend(ex_ts, amount)`, right, steps. No default for the rate or dividends; `solve_row` raises if an American row gets
  `dividends=None` (pass `()`). A dividend counts only when valuation < ex-date < expiry. Present value at or above spot is an error.
- Dividends, escrowed method: the tree runs on S* = spot less the present value of dividends in the option's life; the
  exercise value at a node uses S* plus the dividends not yet gone ex. Escrowed amount: sum D exp(-(r - q)(t_div - t)), so the
  forward is S exp((r - q) T) - sum D exp((r - q)(T - t_div)) (QuantLib's convention; plain present value when q = 0).
  APPROXIMATION: the vol is the vol of S*, not of the quote; the real price jumps on the ex-date. Known weakness (Haug, Haug
  and Lewis): one vol for S* and S misprices, most for large dividends and long expiries. The ex-date falls between nodes, so
  the last exercise before it is up to one step early. Measured at 500 steps over one year: 7.4e-3 for a 2.00 dividend 11 days
  before expiry (bound 0.02, tested), under 2e-3 for an ex-date far from expiry. Use more steps for an ex-date near expiry.

## American style: greeks, implied volatility and cost

- Delta and gamma from the tree's first levels (step-1 slope; change of step-2 slopes), averaged over N and N + 1. A 3% spot
  bump was 10 to 100 times worse (gamma 5.2e-3 off near a put's exercise boundary). Bumps: vol 0.01 (vega per 1.00, central),
  rate 0.005 (rho per 1.00, central), valuation instant one day (theta per calendar day, central). Same units as the closed
  form; the `Conventions` record is shared, and the result says `method="crr_tree"` and its `steps`.
  Noise at 500 steps against the closed form: price 2.5e-4, delta 9e-5, gamma 2.3e-5 (true 0.019), vega 2e-3, rho 0.011.
  If a bumped tree breaks no-arbitrage, `computed` keeps the IV only and `RowSolve.labels` is `("greeks_not_available",)`.
- Bounds: lower is the immediate exercise value (max(S - K, 0) call, max(K - S, 0) put); upper is S (call) or K (put). A price
  at or below the exercise value, or at or above the cap, is `price_outside_no_arbitrage_bounds`. Search interval is
  [max(1e-4, 1.01 |r - q| sqrt(T / steps)), 10]; a price no representable vol gives is `implied_vol_outside_search_interval`.
- Same safeguarded Newton with a bracket (slope by forward difference on the tree), vol tolerance 1e-9, same `low_vega` rule.
- Time on the dev machine, pure Python plus numpy (already a dependency): one 500-step tree 5 ms (a price is two trees); one solve about 0.14 s;
  one row with greeks about 0.2 s; 100 contracts about 21 s at 500 steps. Memory is O(steps): no steps x steps array.
  Pass `steps` to `solve_row` for a coarser chain.
- Model tag: `crr-tree-escrowed-v1;model=crr_tree;steps=<n>;r=<rate>;q=<yield>;divs=<none or iso:amount|...>;day_count=act365f;`
  `theta=per_calendar_day;vega=per_1.00_vol`. The provided slot is never overwritten.
- Tests: tree error against Black-Scholes falls with steps (1.3e-3, 2.5e-4, 6.2e-5 at 100, 500, 2000) and stays under
  0.1 S vol sqrt(T) / steps on a strike, expiry and vol grid; Hull's put (S 50, K 50,
  r 10%, vol 40%, 5 months; five-step tree 4.49, recomputed here as 4.4885; converged value 4.284 from a 20,000-step separate tree);
  early exercise before an ex-date detected; put-call inequalities; tiny-vol limits; smooth delta and gamma; monotone vol.
- Fixture: `PricedModel(..., american_steps=N, dividends=())` makes American-style contracts priced by the tree; the solver recovers the
  surface from them to 1e-6 at the same steps and dividends. The other fixture modes are unchanged.

## Synthetic fixture

`SyntheticAdapter(seed)` implements `OptionsAdapter` for the generic underlying `AAA`. Chains are deterministic for a seed.
The known surface IV is stored as the provided IV. No real market data or symbols are used.
- Placeholder mode (the default) uses a placeholder price shape and American-style contracts. Its prices are NOT
  arbitrage-free, and a solver cannot recover the stored IV from them. Never use it to judge a pricing or volatility method.
- Model-priced mode (`priced=PricedModel(rate, dividend_yield)`) centres each quote on the Black-Scholes-Merton price at the
  surface IV with a symmetric spread (the larger of one cent and 1% of the price, capped at half the price so the bid stays
  above zero). Contracts are European-style. The solver recovers the surface IV from the mid to 1e-7; 44 of 54 rows are
  stored, and the other 10 are `low_vega`.

## Derived series

`derived.py`, `derived_surface.py`, `derived_params.py` (constants). Readings, no thresholds. Time: ACT/365 years to expiry at 21:00 UTC (the pricer's `t`).
- Unused: expiries under 7 days or 3 quoted strikes. Constant maturity: total variance linear in time across the bracket; one-sided: null, no extrapolation.
- `iv30`: ATM IV at the parity forward (European pair: smallest |C - P|), linear in vol across strikes; no pair or American: strike nearest spot, labelled.
- `iv_rank_252`, `iv_percentile_252`: 252 stored sessions including today; percentile = share strictly below today / 252. Warm-up, gap, flat: null.
- `skew_25d`: put minus call IV at |forward delta| N(d1) = 0.25 (undiscounted, no premium adjustment), linear in delta. `term_slope`: 90-day IV - iv30.
  `iv_minus_rv`: `iv30` minus realized vol: 21 close-to-close log returns, sample std, x sqrt(252) (`annualized_volatility`).
- Dropped quotes: crossed, zero-width, zero-bid (one-sided), stale (over 1 day old). No stored rate or yield: defaults 0; at a true 4% rate iv30 reads
  about 0.1 vol point low (Black-76 discount): pass `--rate`. `known_from` = snapshot `known_at` (rank: latest in window). Reads: `snapshots_as_of` only.

## Not here yet

Health card rows, a provider adapter, the security-id map, delisted names, `occ_symbol`, `deliverable`, parity reading, a context-store join.
