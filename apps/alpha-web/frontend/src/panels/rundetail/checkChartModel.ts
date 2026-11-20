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

export interface DsrBar {
  label: string
  value: number
  from: number
  to: number
  perPeriod: string
  /** The yearly figure; null unless the run recorded the periods in a year. */
  perYear: string | null
}
export interface DsrChart {
  zero: number
  bars: DsrBar[]
  unitNote: string
  probabilityNote: string | null
  summary: string
}

/** The periods in a year the run recorded; null when it did not (no factor is ever assumed). */
function recordedPeriods(manifest: ValidateManifest): number | null {
  const value = (manifest.metadata as Record<string, unknown> | undefined)?.periods_per_year
  return typeof value === 'number' && Number.isFinite(value) && value > 0 ? value : null
}

export function dsrChart(manifest: ValidateManifest): Chart<DsrChart> {
  const d = manifest.dsr
  if (!d) return missing('no deflated Sharpe was recorded for this run')
  if (!finite(d.sharpe) || !finite(d.expected_max_sharpe)) return missing('the Sharpe or the luck level is missing or not a number')
  if (!Number.isInteger(d.n_trials) || d.n_trials < 1) return missing('the number of counted tests was not recorded')
  const [lo, hi] = scaleOf([d.sharpe, d.expected_max_sharpe], true)
  const zero = frac(0, lo, hi)
  const periods = recordedPeriods(manifest)
  const bar = (label: string, value: number): DsrBar => ({
    label, value, from: zero, to: frac(value, lo, hi), perPeriod: fmtNum(value, 3), perYear: periods === null ? null : fmtNum(value * Math.sqrt(periods), 2),
  })
  const tests = `${d.n_trials} counted ${d.n_trials === 1 ? 'test' : 'tests'}`
  const bars = [bar("this strategy's Sharpe", d.sharpe), bar(`best Sharpe expected from luck across ${tests}`, d.expected_max_sharpe)]
  const yearly = periods === null ? '' : ` Figures in brackets are per year: the per-period figure times the square root of the ${periods} periods in a year the run recorded.`
  const probability = finite(d.dsr) ? `The deflated Sharpe (${fmtNum(d.dsr, 3)}) is a probability from 0 to 1, not a Sharpe ratio.` : null
  const years = (b: DsrBar): string => (b.perYear === null ? '' : `, ${b.perYear} per year`)
  return {
    status: 'ok', zero, bars, unitNote: `Both bars are Sharpe per trading period, drawn on one scale.${yearly}`, probabilityNote: probability,
    summary: `This strategy's Sharpe ${bars[0].perPeriod} per trading period${years(bars[0])}, against ${bars[1].perPeriod}${years(bars[1])}, the best Sharpe expected from luck across ${tests}.${probability ? ` ${probability}` : ''}`,
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
  barName: string
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
    barName: 'bar: mean ± one standard deviation',
    note: `${c.n_folds} splits; the Sharpe of each split is not stored, only this summary`,
    summary: `Mean Sharpe across ${c.n_folds} splits ${fmtNum(c.mean_sharpe)}, spread (one standard deviation) ${fmtNum(c.std_sharpe)}.${share}`,
  }
}
