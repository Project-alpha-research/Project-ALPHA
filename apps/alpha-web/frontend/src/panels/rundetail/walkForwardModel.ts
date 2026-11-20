// Pure model for the walk-forward chart. The price carries the meaning: one shaded band per fold's tested
// period, with the fold's out-of-sample Sharpe in it. Under the price a staircase draws each fold's own
// warm-up then its tested part. Everything comes from the run's recorded fold dates; the price is the only
// outside input and it is drawn only inside the run's own dates. Positions are fractions 0..1.

import { fmtNum, isFiniteNum as finite } from '../../util/format'
import type { ValidateManifest } from '../../explain/types'
import { frac, type Chart, type PriceBar } from './checkChartModel'

interface FoldDates {
  index: number
  trainStart: number
  trainEnd: number
  testStart: number
  testEnd: number
}
export interface Overlap {
  index: number
  from: number
  to: number
}

/** A fold whose training dates run past the start of its own tested dates. Touching is not overlap. */
export function findOverlaps(folds: readonly FoldDates[]): Overlap[] {
  return folds
    .filter((f) => f.trainEnd > f.testStart)
    .map((f) => ({ index: f.index, from: f.testStart, to: Math.min(f.trainEnd, f.testEnd) }))
}

export interface FoldView {
  /** 1, 2, 3 ... by position. */
  fold: number
  trainX0: number
  trainX1: number
  testX0: number
  testX1: number
  sharpe: number | null
  /** "Sharpe -1.2", printed in the band when it is wide enough. */
  label: string
  /** Hover and focus text. */
  title: string
  /** Two alternating tints. */
  tint: 0 | 1
  /** The shared dates when this fold's warm-up runs into its own tested part. */
  overlap: { x0: number; x1: number } | null
}

export interface WalkForward {
  t0: number
  t1: number
  price: { x: number; y: number }[]
  priceLow: number | null
  priceHigh: number | null
  priceTicks: { y: number; label: string }[]
  priceNote: string | null
  trainLabel: string
  intro: string | null
  folds: FoldView[]
  /** Where the first tested band starts; the price before it is "before the first test". */
  firstTestX: number
  yearTicks: { x: number; label: string }[]
  overlaps: { fold: number; x0: number; x1: number }[]
  warning: string | null
  collapsible: boolean
  skipped: number
  summary: string
}

const TRAIN_LABELS: Record<string, string> = {
  fixed_rule_evaluation_no_refit: 'warm-up: rules fixed, nothing re-tuned',
  fold_by_fold_refit: 'rules tuned here',
}
export const NO_REFIT_SENTENCE = 'The rules never change in this test. Each block is a later stretch of price the rules had not been run on.'
export const COLLAPSE_ABOVE = 8
const isoDay = (ms: number): string => new Date(ms).toISOString().slice(0, 10)
const toMs = (value: unknown): number => (typeof value === 'string' ? Date.parse(value) : Number.NaN)

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

function whyNoPrice(manifest: ValidateManifest, anyBars: boolean): string {
  const symbol = (manifest.metadata as Record<string, unknown> | undefined)?.symbol
  if (typeof symbol !== 'string' || !symbol) return 'price not available: the run does not name its asset'
  const store = (manifest as { spine?: { store?: unknown } }).spine?.store
  if (store !== undefined && store !== 'home') return `price not available: the run's bars are not in the home store, so none are drawn for ${symbol}`
  return anyBars ? `price not available: no stored bars for ${symbol} in these dates` : `price not available: no stored bars for ${symbol}`
}

/** January 1st ticks inside the window, thinned to at most 8. */
function yearTicksOf(t0: number, t1: number): { x: number; label: string }[] {
  const first = new Date(t0).getUTCFullYear() + 1
  const last = new Date(t1).getUTCFullYear()
  const step = Math.max(1, Math.ceil((last - first + 1) / 8))
  const ticks: { x: number; label: string }[] = []
  for (let year = first; year <= last; year += 1) {
    const at = Date.UTC(year, 0, 1)
    if (year % step === 0 && at > t0 && at <= t1) ticks.push({ x: frac(at, t0, t1), label: String(year) })
  }
  return ticks
}

function readFolds(manifest: ValidateManifest): { folds: (FoldDates & { sharpe: number | null })[]; skipped: number } {
  const folds: (FoldDates & { sharpe: number | null })[] = []
  let skipped = 0
  ;(manifest.folds ?? []).forEach((row, at) => {
    const d = [toMs(row.train_start_ts), toMs(row.train_end_ts), toMs(row.test_start_ts), toMs(row.test_end_ts)]
    if (!(d.every(Number.isFinite) && d[0] <= d[1] && d[2] <= d[3])) {
      skipped += 1
      return
    }
    folds.push({ index: row.index ?? at, trainStart: d[0], trainEnd: d[1], testStart: d[2], testEnd: d[3], sharpe: finite(row.oos_sharpe) ? row.oos_sharpe : null })
  })
  return { folds, skipped }
}

const digitsFor = (span: number): number => (span >= 20 ? 0 : span >= 2 ? 1 : 2)

function summaryOf(t0: number, t1: number, trainLabel: string, folds: FoldView[], notes: string[]): string {
  const sharpes = folds.map((f) => `window ${f.fold} ${f.sharpe === null ? 'no Sharpe' : fmtNum(f.sharpe)}`).join(', ')
  return (
    `Price of the asset from ${isoDay(t0)} to ${isoDay(t1)}, with one shaded band for each of ${folds.length} tested windows. ` +
    `${trainLabel} before each of ${folds.length} tested windows ("tested here, not seen before"). Out-of-sample Sharpe: ${sharpes}.` +
    notes.map((n) => ` ${n}`).join('')
  )
}

export function walkForwardChart(manifest: ValidateManifest, bars: readonly PriceBar[] | null, maxPoints = 240): Chart<WalkForward> {
  const { folds: rows, skipped } = readFolds(manifest)
  if (!rows.length) return { status: 'not-recorded', reason: 'the fold dates were not recorded for this run' }
  const t0 = Math.min(...rows.map((f) => f.trainStart))
  const t1 = Math.max(...rows.map((f) => f.testEnd))
  const line = priceLine(bars, t0, t1, maxPoints)
  const x = (ms: number): number => frac(ms, t0, t1)
  const overlapped = new Map(findOverlaps(rows).map((o) => [o.index, { x0: x(o.from), x1: x(o.to) }]))
  const folds: FoldView[] = rows.map((f, at) => ({
    fold: at + 1, trainX0: x(f.trainStart), trainX1: x(f.trainEnd), testX0: x(f.testStart), testX1: x(f.testEnd), sharpe: f.sharpe,
    label: f.sharpe === null ? 'Sharpe not recorded' : `Sharpe ${fmtNum(f.sharpe, 1)}`,
    title: `fold ${at + 1}: tested ${isoDay(f.testStart)} to ${isoDay(f.testEnd)}; out-of-sample Sharpe ${f.sharpe === null ? 'not recorded' : fmtNum(f.sharpe)}`,
    tint: at % 2 === 0 ? 0 : 1, overlap: overlapped.get(f.index) ?? null,
  }))
  const trainLabel = TRAIN_LABELS[manifest.oos_semantics ?? ''] ?? 'training window'
  const overlaps = folds.flatMap((f, at) => (f.overlap ? [{ fold: at + 1, ...f.overlap }] : []))
  const warning = overlaps.length ? 'tuned and tested periods overlap' : null
  const priceNote = line ? null : whyNoPrice(manifest, (bars ?? []).length > 0)
  const notes = [warning ? 'Warning: tuned and tested periods overlap.' : '', priceNote ? `${priceNote}.` : '', skipped ? `${skipped} fold(s) had unreadable dates.` : '']
  const digits = line ? digitsFor(line.high - line.low) : 0
  return {
    status: 'ok', t0, t1, price: line?.price ?? [], priceLow: line?.low ?? null, priceHigh: line?.high ?? null,
    priceTicks: line ? [0, 0.5, 1].map((y) => ({ y, label: fmtNum(line.low + y * (line.high - line.low), digits) })) : [],
    priceNote, trainLabel, intro: manifest.oos_semantics === 'fixed_rule_evaluation_no_refit' ? NO_REFIT_SENTENCE : null,
    folds, firstTestX: Math.min(...folds.map((f) => f.testX0)), yearTicks: yearTicksOf(t0, t1), overlaps, warning,
    collapsible: folds.length > COLLAPSE_ABOVE, skipped, summary: summaryOf(t0, t1, trainLabel, folds, notes.filter(Boolean)),
  }
}

export interface StairRows {
  top: FoldView[]
  bottom: FoldView[]
  hidden: number
  total: number
}

/** All rows when there are 8 or fewer folds or when asked; else the first 3 and last 2. */
export function staircaseRows(folds: readonly FoldView[], expanded: boolean): StairRows {
  if (expanded || folds.length <= COLLAPSE_ABOVE) return { top: [...folds], bottom: [], hidden: 0, total: folds.length }
  return { top: folds.slice(0, 3), bottom: folds.slice(-2), hidden: folds.length - 5, total: folds.length }
}

const CHAR_PX = 5.6

/** The words that fit a band: "Sharpe -1.2" on one line, else "Sharpe" over the number, else the number, else nothing (hover or focus shows it). */
export function bandLines(f: FoldView, widthPx: number): string[] | null {
  if (widthPx >= f.label.length * CHAR_PX + 8) return [f.label]
  if (f.sharpe === null) return widthPx >= 6 * CHAR_PX + 6 ? ['no', 'Sharpe'] : null
  const number = f.label.slice('Sharpe '.length)
  if (widthPx >= Math.max(6 * CHAR_PX, number.length * CHAR_PX) + 6) return ['Sharpe', number]
  return widthPx >= number.length * CHAR_PX + 4 ? [number] : null
}
