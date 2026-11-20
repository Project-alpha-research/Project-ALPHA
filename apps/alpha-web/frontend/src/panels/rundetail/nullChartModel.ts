// Pure model for the randomized-price chart: one picture of the stored random-run Sharpes per tier,
// with this strategy's recorded Sharpe marked. From 20 draws up it is a histogram; below that it is one
// tick per draw on a number line, because a few bars would only look like a shape that is not there. The draws are the run's own `nulls.parquet`
// values; the share of random runs that did as well is the recorded p-value, not a recount.

import { fmtNum, fmtPct, isFiniteNum as finite } from '../../util/format'
import type { NullTiers } from '../../api/types'
import type { ValidateManifest } from '../../explain/types'
import { frac, scaleOf, type NotRecorded } from './checkChartModel'

export interface Bins {
  edges: number[]
  counts: number[]
}

/** Equal-width bins over the draws, stretched to hold `include` when given. The largest value falls in the last bin. */
export function histogramBins(values: readonly number[], nBins: number, include?: number): Bins {
  let lo = Math.min(...values, ...(include === undefined ? [] : [include]))
  let hi = Math.max(...values, ...(include === undefined ? [] : [include]))
  if (hi === lo) {
    const half = Math.abs(lo) > 0 ? Math.abs(lo) * 0.5 : 0.5
    lo -= half
    hi += half
  }
  const width = (hi - lo) / nBins
  const counts = new Array<number>(nBins).fill(0)
  for (const v of values) counts[Math.min(nBins - 1, Math.floor((v - lo) / width))] += 1
  return { edges: Array.from({ length: nBins + 1 }, (_, i) => lo + i * width), counts }
}

/** Fewer draws than this are drawn one by one, not binned. */
export const STRIP_BELOW = 20

export interface NullTierChart {
  tier: string
  /** The plain name of the tier. */
  title: string
  /** "20 random series". */
  detail: string
  nDraws: number
  mode: 'histogram' | 'strip'
  /** Bar heights, 0..1 of the tallest bar (histogram only). */
  heights: number[]
  /** One position per draw, 0..1 of the drawn range (strip only). */
  ticks: number[]
  /** "only 4 random series: a rough picture" for a strip. */
  roughNote: string | null
  /** This strategy's Sharpe, as a fraction 0..1 of the drawn range. */
  marker: number
  observed: number
  low: number
  high: number
  shareAsGood: number | null
  summary: string
}

export type NullCharts = { status: 'ok'; tiers: NullTierChart[]; skipped: string[] } | NotRecorded

const TIER_NAMES: Record<string, string> = {
  returns_level: 'quick version',
  full_engine: 'real engine on random prices',
  bar_permutation: "this run's own bars shuffled",
}

export const missingDraws = 'the random-price draws were not recorded for this run'

export function nullCharts(manifest: ValidateManifest, draws: NullTiers | null): NullCharts {
  if (!draws) return { status: 'not-recorded', reason: missingDraws }
  const tiers: NullTierChart[] = []
  const skipped: string[] = []
  for (const row of manifest.nulls ?? []) {
    const stats = (draws.tiers.find((t) => t.tier === row.tier)?.statistics ?? []).filter(finite)
    if (!stats.length || !finite(row.observed)) {
      skipped.push(row.tier)
      continue
    }
    const share = finite(row.p_value) ? row.p_value : null
    const strip = stats.length < STRIP_BELOW
    const bins = strip ? null : histogramBins(stats, Math.max(8, Math.min(24, Math.ceil(Math.sqrt(stats.length)))), row.observed)
    const [low, high] = bins ? [bins.edges[0], bins.edges[bins.edges.length - 1]] : scaleOf([...stats, row.observed], false)
    const top = bins ? Math.max(...bins.counts) : 1
    const title = TIER_NAMES[row.tier] ?? row.tier
    const detail = `${stats.length} random series`
    const rough = strip ? `only ${stats.length} random series: a rough picture` : null
    tiers.push({
      tier: row.tier, title, detail, nDraws: stats.length, mode: strip ? 'strip' : 'histogram',
      heights: bins ? bins.counts.map((n) => n / top) : [], ticks: strip ? stats.map((v) => frac(v, low, high)) : [], roughNote: rough,
      marker: frac(row.observed, low, high), observed: row.observed, low, high, shareAsGood: share,
      summary: `${title}, ${rough ?? detail}: this strategy ${fmtNum(row.observed)}` + (share === null ? '' : `; random data did as well in ${fmtPct(share, 1)} of draws`),
    })
  }
  if (!tiers.length) return { status: 'not-recorded', reason: missingDraws }
  return { status: 'ok', tiers, skipped }
}
