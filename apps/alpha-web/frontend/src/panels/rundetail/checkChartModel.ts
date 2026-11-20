// Pure models for the small chart on each Gates card. Each reads only what the run recorded and
// returns either a chart (positions as fractions 0..1) or "not recorded" with the reason. Nothing is
// recomputed and no number is invented: a missing or non-finite input never draws an empty chart.

import { fmtNum, fmtPct, isFiniteNum as finite } from '../../util/format'
import type { ValidateManifest } from '../../explain/types'

export interface NotRecorded {
  status: 'not-recorded'
  reason: string
}
export type Chart<T> = ({ status: 'ok' } & T) | NotRecorded

/** One recorded price bar: epoch seconds and the close. */
export interface PriceBar {
  t: number
  c: number
}

const missing = (reason: string): NotRecorded => ({ status: 'not-recorded', reason })

/** Where `value` sits between `lo` and `hi`, 0..1. */
export const frac = (value: number, lo: number, hi: number): number => (hi > lo ? (value - lo) / (hi - lo) : 0.5)

/** A scale that holds every value, plus zero when asked, with 8% padding each side. */
export function scaleOf(values: readonly number[], includeZero: boolean): [number, number] {
  const all = includeZero ? [...values, 0] : [...values]
  let lo = Math.min(...all)
  let hi = Math.max(...all)
  if (hi === lo) {
    lo -= 0.5
    hi += 0.5
  }
  const pad = (hi - lo) * 0.08
  return [lo - pad, hi + pad]
}

// ---- walk-forward ------------------------------------------------------------------------

export interface Overlap {
  index: number
  from: number
  to: number
}
interface FoldDates {
  index: number
  trainStart: number
  trainEnd: number
  testStart: number
  testEnd: number
}

/** A fold whose training dates run past the start of its own tested dates. Touching is not overlap. */
export function findOverlaps(folds: readonly FoldDates[]): Overlap[] {
  return folds
    .filter((f) => f.trainEnd > f.testStart)
    .map((f) => ({ index: f.index, from: f.testStart, to: Math.min(f.trainEnd, f.testEnd) }))
}

export interface WalkForward {
  t0: number
  t1: number
  price: { x: number; y: number }[]
  priceLow: number | null
  priceHigh: number | null
  priceNote: string | null
  trainLabel: string
  trainBands: { x0: number; x1: number }[]
  testBands: { fold: number; x0: number; x1: number; sharpe: number | null }[]
  overlaps: { fold: number; x0: number; x1: number }[]
  warning: string | null
  skipped: number
  summary: string
}

const TRAIN_LABELS: Record<string, string> = {
  fixed_rule_evaluation_no_refit: 'warm-up window: rules fixed, nothing re-tuned',
  fold_by_fold_refit: 'rules tuned here',
}
const isoDay = (ms: number): string => new Date(ms).toISOString().slice(0, 10)
const toMs = (value: unknown): number => (typeof value === 'string' ? Date.parse(value) : Number.NaN)

function mergeBands(bands: { x0: number; x1: number }[]): { x0: number; x1: number }[] {
  const merged: { x0: number; x1: number }[] = []
  for (const band of [...bands].sort((a, b) => a.x0 - b.x0)) {
    const last = merged[merged.length - 1]
    if (last && band.x0 <= last.x1) last.x1 = Math.max(last.x1, band.x1)
    else merged.push({ ...band })
  }
  return merged
}

function priceLine(bars: readonly PriceBar[] | null, t0: number, t1: number, maxPoints: number) {
  const kept = (bars ?? []).filter((b) => finite(b.t) && finite(b.c) && b.t * 1000 >= t0 && b.t * 1000 <= t1).sort((a, b) => a.t - b.t)
  if (!kept.length) return null
  const step = Math.max(1, Math.ceil(kept.length / maxPoints))
  const thinned = kept.filter((_, i) => i % step === 0)
  if (thinned[thinned.length - 1] !== kept[kept.length - 1]) thinned.push(kept[kept.length - 1])
  const low = Math.min(...kept.map((b) => b.c))
  const high = Math.max(...kept.map((b) => b.c))
  const price = thinned.map((b) => ({ x: frac(b.t * 1000, t0, t1), y: frac(b.c, low, high) }))
  return { price, low, high }
}

function readFolds(manifest: ValidateManifest): { folds: (FoldDates & { sharpe: number | null })[]; skipped: number } {
  const rows = manifest.folds ?? []
  const folds: (FoldDates & { sharpe: number | null })[] = []
  let skipped = 0
  rows.forEach((row, at) => {
    const dates = [toMs(row.train_start_ts), toMs(row.train_end_ts), toMs(row.test_start_ts), toMs(row.test_end_ts)]
    const ordered = dates.every(Number.isFinite) && dates[0] <= dates[1] && dates[2] <= dates[3]
    if (!ordered) {
      skipped += 1
      return
    }
    folds.push({
      index: row.index ?? at, trainStart: dates[0], trainEnd: dates[1], testStart: dates[2], testEnd: dates[3],
      sharpe: finite(row.oos_sharpe) ? row.oos_sharpe : null,
    })
  })
  return { folds, skipped }
}

export function walkForwardChart(manifest: ValidateManifest, bars: readonly PriceBar[] | null, maxPoints = 240): Chart<WalkForward> {
  const { folds, skipped } = readFolds(manifest)
  if (!folds.length) return missing('the fold dates were not recorded for this run')
  const t0 = Math.min(...folds.map((f) => f.trainStart))
  const t1 = Math.max(...folds.map((f) => f.testEnd))
  const line = priceLine(bars, t0, t1, maxPoints)
  const x = (ms: number): number => frac(ms, t0, t1)
  const overlaps = findOverlaps(folds).map((o) => ({ fold: o.index, x0: x(o.from), x1: x(o.to) }))
  const trainLabel = TRAIN_LABELS[manifest.oos_semantics ?? ''] ?? 'training window'
  const testBands = folds.map((f) => ({ fold: f.index, x0: x(f.testStart), x1: x(f.testEnd), sharpe: f.sharpe }))
  const sharpes = testBands.map((b) => `window ${b.fold + 1} ${b.sharpe === null ? 'no Sharpe' : fmtNum(b.sharpe)}`).join(', ')
  const summary =
    `Price of the asset from ${isoDay(t0)} to ${isoDay(t1)}. ${trainLabel} before each of ${folds.length} tested windows ` +
    `("tested here, not seen before"). Out-of-sample Sharpe: ${sharpes}.` +
    (overlaps.length ? ' Warning: tuned and tested periods overlap.' : '') +
    (line ? '' : ' The price line was not recorded.') + (skipped ? ` ${skipped} fold(s) had unreadable dates.` : '')
  return {
    status: 'ok', t0, t1, price: line?.price ?? [], priceLow: line?.low ?? null, priceHigh: line?.high ?? null,
    priceNote: line ? null : 'price line not recorded for this run', trainLabel,
    trainBands: mergeBands(folds.map((f) => ({ x0: x(f.trainStart), x1: x(f.trainEnd) }))),
    testBands, overlaps, warning: overlaps.length ? 'tuned and tested periods overlap' : null, skipped, summary,
  }
}

// ---- bootstrap interval ------------------------------------------------------------------

export interface IntervalChart {
  lower: number
  upper: number
  point: number
  zero: number
  includesZero: boolean
  confidencePct: string
  values: { lower: number; upper: number; point: number }
  summary: string
}

export function ciChart(manifest: ValidateManifest): Chart<IntervalChart> {
  const row = manifest.cis?.find((c) => c.metric === 'sharpe')
  if (!row) return missing('no Sharpe interval was recorded for this run')
  const { lower, upper, point } = row
  if (!finite(lower) || !finite(upper) || !finite(point)) return missing('the Sharpe interval has a missing or non-finite end')
  if (lower > upper) return missing('the recorded interval ends are out of order')
  const [lo, hi] = scaleOf([lower, upper, point], true)
  const includesZero = lower <= 0 && upper >= 0
  const pct = fmtPct(row.confidence, 0)
  const where = includesZero ? 'the interval includes zero' : lower > 0 ? 'the interval is above zero' : 'the interval is below zero'
  return {
    status: 'ok', lower: frac(lower, lo, hi), upper: frac(upper, lo, hi), point: frac(point, lo, hi), zero: frac(0, lo, hi),
    includesZero, confidencePct: pct, values: { lower, upper, point },
    summary: `Sharpe ${fmtNum(point)}; ${pct} interval from ${fmtNum(lower)} to ${fmtNum(upper)}; ${where}.`,
  }
}

// ---- deflated Sharpe ---------------------------------------------------------------------

export interface DsrChart {
  zero: number
  bars: { label: string; value: number; from: number; to: number }[]
  unitNote: string
  summary: string
}

export function dsrChart(manifest: ValidateManifest): Chart<DsrChart> {
  const d = manifest.dsr
  if (!d) return missing('no deflated Sharpe was recorded for this run')
  if (!finite(d.sharpe) || !finite(d.expected_max_sharpe)) return missing('the Sharpe or the luck level is missing or not a number')
  if (!Number.isInteger(d.n_trials) || d.n_trials < 1) return missing('the number of counted tests was not recorded')
  const [lo, hi] = scaleOf([d.sharpe, d.expected_max_sharpe], true)
  const zero = frac(0, lo, hi)
  const bar = (label: string, value: number) => ({ label, value, from: zero, to: frac(value, lo, hi) })
  const tests = `${d.n_trials} counted ${d.n_trials === 1 ? 'test' : 'tests'}`
  const bars = [bar("this strategy's Sharpe", d.sharpe), bar(`best Sharpe expected from luck across ${tests}`, d.expected_max_sharpe)]
  return {
    status: 'ok', zero, bars, unitNote: 'Sharpe per trading period, not per year',
    summary: `This strategy's Sharpe ${fmtNum(d.sharpe, 3)} against ${fmtNum(d.expected_max_sharpe, 3)}, the best Sharpe expected from luck across ${tests} (per trading period).`,
  }
}

// ---- combinatorial cross-validation ------------------------------------------------------

export interface CpcvChart {
  mode: 'summary'
  zero: number
  mean: number
  low: number
  high: number
  values: { mean: number; low: number; high: number }
  note: string
  summary: string
}

export function cpcvChart(manifest: ValidateManifest): Chart<CpcvChart> {
  const c = manifest.cpcv
  if (!c) return missing('no cross-validation summary was recorded for this run')
  if (!Number.isInteger(c.n_folds) || c.n_folds < 1) return missing('no cross-validation splits were recorded')
  if (!finite(c.mean_sharpe) || !finite(c.std_sharpe) || c.std_sharpe < 0) return missing('the mean or spread of the split Sharpes is missing or not a number')
  const [lo, hi] = scaleOf([c.mean_sharpe - c.std_sharpe, c.mean_sharpe + c.std_sharpe], true)
  const share = finite(c.frac_positive) ? ` ${fmtPct(c.frac_positive, 0)} of splits above zero.` : ''
  return {
    status: 'ok', mode: 'summary', zero: frac(0, lo, hi), mean: frac(c.mean_sharpe, lo, hi),
    low: frac(c.mean_sharpe - c.std_sharpe, lo, hi), high: frac(c.mean_sharpe + c.std_sharpe, lo, hi),
    values: { mean: c.mean_sharpe, low: c.mean_sharpe - c.std_sharpe, high: c.mean_sharpe + c.std_sharpe },
    note: `${c.n_folds} splits; the Sharpe of each split is not stored, only this summary`,
    summary: `Mean Sharpe across ${c.n_folds} splits ${fmtNum(c.mean_sharpe)}, spread (one standard deviation) ${fmtNum(c.std_sharpe)}.${share}`,
  }
}
