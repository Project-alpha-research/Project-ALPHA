// Gate stories: turn each validation check's numbers into an explanation in both voices.
// Pure functions over the manifest — no fetches, no DOM — so the whole module unit-tests in node.
// A check is a FACT check (is the test valid: a state word, sound / fault / not checked) or a STAT
// check (how strong is the evidence: numbers, the plain comparison, and the level the old grade used,
// shown muted). Nothing here says passed or failed, and no card is coloured good or bad. The classes
// have one home: docs/reference/invariants/cli-rule-readings.md.

import { fmtNum, fmtPct, isFiniteNum as finite } from '../util/format'
import type {
  CIRow,
  CPCVBlock,
  DSRBlock,
  FoldRow,
  GateStory,
  NullTierRow,
  ValidateManifest,
} from './types'

const OLD = 'The level used by the old grade: '
type Fixed = Pick<GateStory, 'kind' | 'state' | 'oldLevel' | 'tone'>
const stat = (level: string | null): Fixed => ({ kind: 'stat', state: null, oldLevel: level === null ? null : OLD + level, tone: 'info' })
const fact = (passed: boolean | null): Fixed => ({
  kind: 'fact', state: passed === null ? 'not-checked' : passed ? 'sound' : 'fault', oldLevel: null, tone: 'info',
})

// ---- gate: walk_forward_oos ----------------------------------------------------------------

export function walkForwardStory(m: ValidateManifest): GateStory {
  const folds: FoldRow[] = m.folds ?? []
  const sharpe = m.oos_metrics?.sharpe ?? null
  const passed = m.outcomes?.find((o) => o.name === 'walk_forward_oos')?.passed ?? null
  const nOos = folds.reduce((acc, f) => acc + (f.n_test || 0), 0)
  const positive = folds.filter((f) => finite(f.oos_sharpe) && f.oos_sharpe > 0).length
  const graded = folds.filter((f) => finite(f.oos_sharpe)).length
  const years = nOos > 0 ? nOos / 252 : 0

  const narrative =
    `The strategy traded ${folds.length} out-of-sample windows in sequence — a total of ` +
    `${nOos.toLocaleString()} sessions (~${fmtNum(years, 1)} years) it never saw during warmup. ` +
    `Stitched together they earn an annualized Sharpe of ${fmtNum(sharpe)}. ` +
    `${positive} of ${graded} windows had a positive Sharpe` +
    (graded < folds.length ? ` (${folds.length - graded} flat windows carry no Sharpe)` : '') +
    `. Consistency across windows matters more than the average: an edge that only lived in one ` +
    `regime shows up here as a few great folds drowning many flat ones.`

  return {
    gate: 'walk_forward_oos',
    title: 'Walk-forward out-of-sample',
    passed,
    plain: finite(sharpe)
      ? `The out-of-sample Sharpe is ${fmtNum(sharpe)} over ${folds.length} windows, with ${positive} of ${graded} windows above zero.`
      : 'No out-of-sample Sharpe was produced, so this check could not be computed.',
    tests:
      'Is there any out-of-sample performance to talk about? The series is split into rolling ' +
      'train/test windows (train = warmup only — nothing refits); the concatenated test windows ' +
      'form the single OOS stream every other check reads. This is a fact check: it is sound when a finite OOS Sharpe was produced.',
    stats: [
      { label: 'OOS Sharpe', value: fmtNum(sharpe), term: 'sharpe' },
      { label: 'Folds', value: String(folds.length), term: 'walk_forward' },
      { label: 'Folds above zero', value: `${positive}/${graded}` },
      { label: 'OOS sessions', value: nOos.toLocaleString() },
    ],
    terse: `OOS Sharpe ${fmtNum(sharpe)} over ${folds.length} folds (${positive}/${graded} positive), n=${nOos}.`,
    narrative,
    ...fact(passed),
  }
}

// ---- gate: randomized_price_null -----------------------------------------------------------

export function nullStory(m: ValidateManifest): GateStory {
  const tiers: NullTierRow[] = m.nulls ?? []
  const t1 = tiers.find((t) => t.tier === 'returns_level') ?? null
  const t2 = tiers.find((t) => t.tier === 'full_engine') ?? null
  const t3 = tiers.find((t) => t.tier === 'bar_permutation') ?? null
  const passed = m.outcomes?.find((o) => o.name === 'randomized_price_null')?.passed ?? null
  const flagged = t1?.flagged_low_fidelity ?? false

  const tierLine = (t: NullTierRow | null, label: string): string =>
    t
      ? `${label}: the observed Sharpe ${fmtNum(t.observed)} lands at the ` +
        `${fmtPct(t.percentile, 1)} percentile of ${t.n_paths.toLocaleString()} no-edge paths ` +
        `(p = ${fmtNum(t.p_value, 3)}): random data did as well in ${fmtPct(t.p_value, 1)} of draws. `
      : ''

  const engineTiers = [t2, t3].filter((t): t is NullTierRow => t !== null)
  const vetoed = engineTiers.filter((t) => !t.passed).map((t) => t.tier)
  let narrative =
    `The luck test. Every tier asks the same question — would random, edge-free prices have paid ` +
    `this well? — at different fidelity. ` +
    tierLine(t1, 'Tier 1 (fast surrogate, resampled returns)') +
    tierLine(t2, 'Tier 2 (real engine, synthetic OHLCV)') +
    tierLine(t3, 'Tier 3 (real engine, the OOS bars permuted)')
  if (flagged) {
    narrative +=
      `Tier 1 is marked advisory: its close-fill convention differs from the engine's ` +
      `t+1-open fills by ${fmtNum(t1?.convention_divergence)} Sharpe (more than the stated ` +
      `tolerance) while Tier 2, the honest simulation, held. Read this as a limit of the ` +
      `surrogate, not as evidence of luck.`
  } else if (passed === false) {
    narrative +=
      `Random paths with NO edge did about as well as the strategy in more than ` +
      `${fmtPct(1 - (t1?.threshold ?? t2?.threshold ?? 0.95), 0)} of draws, whatever the equity curve looks like, ` +
      `so on this symbol and period the result cannot be told apart from luck.` +
      (vetoed.length ? ` An engine tier is never set aside.` : '')
  } else if (passed) {
    narrative += `Random prices rarely matched this performance: in every tier the share of random runs that did as well was small.`
  }

  const stats: GateStory['stats'] = []
  if (t1) {
    stats.push(
      { label: 'T1 percentile', value: fmtPct(t1.percentile, 1), term: 'null_test' },
      { label: 'T1 p-value', value: fmtNum(t1.p_value, 3), term: 'p_value' },
      { label: 'Divergence', value: fmtNum(t1.convention_divergence, 3), term: 'convention_divergence' },
    )
  }
  if (t2) {
    stats.push(
      { label: 'T2 percentile', value: fmtPct(t2.percentile, 1), term: 'null_test' },
      { label: 'T2 p-value', value: fmtNum(t2.p_value, 3), term: 'p_value' },
      { label: 'T2 paths', value: String(t2.n_paths) },
    )
  }
  if (t3) {
    stats.push(
      { label: 'T3 percentile', value: fmtPct(t3.percentile, 1), term: 'null_test' },
      { label: 'T3 p-value', value: fmtNum(t3.p_value, 3), term: 'p_value' },
      { label: 'T3 paths', value: String(t3.n_paths) },
    )
  }

  const shares = [t1, t2, t3].flatMap((t) => (t && finite(t.p_value) ? [t.p_value] : []))
  const level = t1?.threshold ?? t2?.threshold ?? 0.95
  const plainNull = shares.length
    ? `Random data did as well in ${fmtPct(Math.min(...shares), 0)} to ${fmtPct(Math.max(...shares), 0)} of draws, so this result ` +
      (Math.max(...shares) > 1 - level ? 'cannot be told apart from luck.' : 'stands apart from luck in every tier.')
    : 'not computed: no randomized-price tiers were recorded for this run.'
  return {
    gate: 'randomized_price_null',
    title: 'Randomized-price null (the luck test)',
    passed,
    plain: plainNull,
    tests:
      'Could pure luck explain the performance? The strategy is compared with synthetic no-edge ' +
      'price paths in every tier: a fast returns-level surrogate (1,000 paths), ' +
      'the real engine on synthetic OHLCV (64 paths), and the real engine on permutations of the ' +
      'out-of-sample bars themselves (64 paths). The number to read is the share of random runs that did as well.',
    stats,
    terse:
      `T1 ${t1 ? `${fmtPct(t1.percentile, 0)} pct` : '—'} · ` +
      `T2 ${t2 ? `${fmtPct(t2.percentile, 0)} pct` : '—'}` +
      (t3 ? ` · T3 ${fmtPct(t3.percentile, 0)} pct` : '') +
      (flagged ? ' · T1 advisory (low fidelity)' : ''),
    narrative,
    ...stat(shares.length ? `each tier at the ${fmtPct(level, 0)} percentile or higher` : null),
  }
}

// ---- gate: bootstrap_ci --------------------------------------------------------------------

export function ciStory(m: ValidateManifest): GateStory {
  const ci: CIRow | null = m.cis?.find((c) => c.metric === 'sharpe') ?? null
  const passed = m.outcomes?.find((o) => o.name === 'bootstrap_ci')?.passed ?? null
  const straddles = ci !== null && finite(ci.lower) && finite(ci.upper) && ci.lower < 0 && ci.upper > 0

  const narrative = ci
    ? `Resampling the OOS returns 2,000 times (block bootstrap, BCa-corrected) puts the Sharpe's ` +
      `${fmtPct(ci.confidence, 0)} confidence interval at [${fmtNum(ci.lower)}, ${fmtNum(ci.upper)}] ` +
      `around a point estimate of ${fmtNum(ci.point)}. ` +
      (ci.lower !== null && ci.lower > 0
        ? `Even the pessimistic lower bound is above zero, so the Sharpe does not rest on one lucky stretch.`
        : straddles
          ? `The interval straddles zero: the data cannot rule out that the true Sharpe is negative. ` +
            `This usually means the sample is too short for the edge's size — more history shrinks ` +
            `the interval; a genuinely stronger edge moves it off zero.`
          : `The lower bound sits at or below zero, so a zero-or-worse true Sharpe remains plausible.`)
    : 'No confidence interval was computed for this run.'

  return {
    gate: 'bootstrap_ci',
    title: 'Bootstrap confidence interval',
    passed,
    plain: ci
      ? `The Sharpe interval runs from ${fmtNum(ci.lower)} to ${fmtNum(ci.upper)}, so it ` +
        (ci.lower !== null && ci.lower > 0 ? 'is above zero.' : straddles ? 'includes zero.' : 'is not above zero.')
      : 'not computed: no confidence interval was recorded for this run.',
    tests:
      'How sure are we of the Sharpe itself? A stationary block bootstrap resamples the OOS ' +
      'stream; the number to read is whether the BCa interval includes zero.',
    stats: ci
      ? [
          { label: 'Sharpe', value: fmtNum(ci.point), term: 'sharpe' },
          { label: 'Lower', value: fmtNum(ci.lower), term: 'bca_ci' },
          { label: 'Upper', value: fmtNum(ci.upper), term: 'bca_ci' },
          { label: 'Confidence', value: fmtPct(ci.confidence, 0) },
        ]
      : [],
    terse: ci
      ? `Sharpe ${fmtNum(ci.point)} ∈ [${fmtNum(ci.lower)}, ${fmtNum(ci.upper)}] @ ${fmtPct(ci.confidence, 0)} — the interval ${ci.lower !== null && ci.lower > 0 ? 'is above zero' : straddles ? 'includes zero' : 'is not above zero'}`
      : 'no CI',
    narrative,
    ...stat(ci ? 'lower end above 0' : null),
  }
}

// ---- gate: deflated_sharpe -----------------------------------------------------------------

export function dsrStory(m: ValidateManifest): GateStory {
  const d: DSRBlock | undefined = m.dsr
  const passed = m.outcomes?.find((o) => o.name === 'deflated_sharpe')?.passed ?? d?.passed ?? null
  const single = (d?.n_trials ?? 1) <= 1

  const narrative = d
    ? `The probabilistic Sharpe (PSR) is ${fmtNum(d.psr, 4)} — the probability that the TRUE ` +
      `Sharpe is above zero given this sample's length, skew, and kurtosis. ` +
      (single
        ? `With a single configuration (no parameter sweep) there is nothing to deflate, so DSR ` +
          `equals PSR. `
        : `Deflating for ${d.n_trials} trials (expected best-by-luck Sharpe ` +
          `${fmtNum(d.expected_max_sharpe)}) leaves DSR ${fmtNum(d.dsr, 4)}. `) +
      (d.dsr !== null && d.dsr >= d.threshold
        ? `At or above ${fmtNum(d.threshold, 2)}, the Sharpe is statistically distinguishable from noise.`
        : `Below ${fmtNum(d.threshold, 2)}, on this sample size the observed Sharpe is ` +
          `not yet statistically separable from zero.`)
    : 'No DSR block in this manifest.'

  return {
    gate: 'deflated_sharpe',
    title: 'Deflated / probabilistic Sharpe',
    passed,
    plain: d
      ? `The deflated Sharpe is ${fmtNum(d.dsr, 3)} after counting ${d.n_trials} ${d.n_trials === 1 ? 'try' : 'tries'}, against ${fmtNum(d.threshold, 2)} used by the old grade.`
      : 'not computed: no deflated Sharpe was recorded for this run.',
    tests:
      'Is the Sharpe statistically real, net of sample noise (and of selection when many ' +
      'configurations were tried)? The number to read is the deflated Sharpe.',
    stats: d
      ? [
          { label: 'PSR', value: fmtNum(d.psr, 4), term: 'psr' },
          { label: 'DSR', value: fmtNum(d.dsr, 4), term: 'dsr' },
          { label: 'Trials', value: String(d.n_trials) },
                  ]
      : [],
    terse: d
      ? `PSR ${fmtNum(d.psr, 3)}${single ? ' (=DSR, single trial)' : ` · DSR ${fmtNum(d.dsr, 3)} @ ${d.n_trials} trials`}`
      : 'no DSR',
    narrative,
    ...stat(d ? fmtNum(d.threshold, 2) : null),
  }
}

// ---- gate: cpcv_oos ------------------------------------------------------------------------

export function cpcvStory(m: ValidateManifest): GateStory {
  const c: CPCVBlock | undefined = m.cpcv
  const passed = m.outcomes?.find((o) => o.name === 'cpcv_oos')?.passed ?? c?.passed ?? null

  const narrative = c
    ? `Instead of trusting one chronological path, CPCV re-splits the OOS stream into ` +
      `${c.n_folds} purged, embargoed fold combinations and scores each. Mean fold Sharpe ` +
      `${fmtNum(c.mean_sharpe)} (σ ${fmtNum(c.std_sharpe)}), with ${fmtPct(c.frac_positive, 0)} of ` +
      `folds positive. ` +
      (c.mean_sharpe !== null && c.mean_sharpe > 0
        ? `The mean is above zero, so the Sharpe does not rest on one particular ordering of history.`
        : `A mean at or below zero across combinations says the single walk-forward path flattered ` +
          `the strategy: under re-orderings the Sharpe disappears.`)
    : 'No CPCV block in this manifest.'

  return {
    gate: 'cpcv_oos',
    title: 'Combinatorial purged CV',
    passed,
    plain: c
      ? `Across ${c.n_folds} fold combinations the mean Sharpe is ${fmtNum(c.mean_sharpe)}, with ${fmtPct(c.frac_positive, 0)} of folds above zero.`
      : 'not computed: no combinatorial cross-validation was recorded for this run.',
    tests:
      'Does the edge survive re-orderings of history? The OOS stream is recombined into many ' +
      'purged train/test group combinations; the number to read is the mean fold Sharpe.',
    stats: c
      ? [
          { label: 'Folds', value: String(c.n_folds), term: 'cpcv' },
          { label: 'Mean Sharpe', value: fmtNum(c.mean_sharpe), term: 'sharpe' },
          { label: 'Std', value: fmtNum(c.std_sharpe) },
          { label: 'Frac > 0', value: fmtPct(c.frac_positive, 0) },
        ]
      : [],
    terse: c
      ? `${c.n_folds} folds: mean ${fmtNum(c.mean_sharpe)} ± ${fmtNum(c.std_sharpe)}, ${fmtPct(c.frac_positive, 0)} positive`
      : 'no CPCV',
    narrative,
    ...stat(c ? 'mean fold Sharpe above 0' : null),
  }
}

/** All five gate stories in canonical gate order. */
export function gateStories(m: ValidateManifest): GateStory[] {
  return [walkForwardStory(m), nullStory(m), ciStory(m), dsrStory(m), cpcvStory(m)]
}
