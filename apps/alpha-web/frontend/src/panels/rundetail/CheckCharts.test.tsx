import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { NullTiers } from '../../api/types'
import type { ValidateManifest } from '../../explain/types'
import { BANNED } from '../__fixtures__/scanWords'
import { CpcvView, DsrView, IntervalView, NotAvailable, WalkForwardView } from './CheckCharts'
import { ciChart, cpcvChart, dsrChart, walkForwardChart, type PriceBar } from './checkChartModel'
import { nullCharts } from './nullChartModel'
import { NullView } from './NullChart'

const DAY = 86_400
const T0 = Date.parse('2020-01-01T00:00:00Z') / 1000
const iso = (day: number) => new Date((T0 + day * DAY) * 1000).toISOString()
const fold = (index: number, a: number, b: number, c: number, d: number, sharpe: number | null) =>
  ({ index, n_test: d - c, oos_sharpe: sharpe, train_start_ts: iso(a), train_end_ts: iso(b), test_start_ts: iso(c), test_end_ts: iso(d) })
const manifest = {
  oos_semantics: 'fixed_rule_evaluation_no_refit',
  folds: [fold(0, 0, 120, 105, 200, 1.5), fold(1, 100, 200, 205, 300, -0.4)],
  cis: [{ metric: 'sharpe', confidence: 0.95, point: 0.5, lower: -0.2, upper: 1.4 }],
  dsr: { sharpe: 0.08, psr: 0.9, dsr: 0.9, expected_max_sharpe: 0.05, n_trials: 12, threshold: 0.95, passed: false },
  cpcv: { n_folds: 15, mean_sharpe: 1.2, std_sharpe: 0.5, frac_positive: 0.8, passed: true },
  nulls: [{ tier: 'returns_level', observed: 0.8, percentile: 0.97, p_value: 0.03, threshold: 0.95, passed: true, n_paths: 60, convention_divergence: null, flagged_low_fidelity: false }],
} as unknown as ValidateManifest
const bars: PriceBar[] = Array.from({ length: 301 }, (_, i) => ({ t: T0 + i * DAY, c: 100 + i }))
const draws: NullTiers = { tiers: [{ tier: 'returns_level', statistics: Array.from({ length: 60 }, (_, i) => i / 30 - 1) }] }

function views(): string[] {
  const walk = walkForwardChart(manifest, bars)
  const ci = ciChart(manifest)
  const dsr = dsrChart(manifest)
  const cpcv = cpcvChart(manifest)
  const nulls = nullCharts(manifest, draws)
  if (walk.status !== 'ok' || ci.status !== 'ok' || dsr.status !== 'ok' || cpcv.status !== 'ok' || nulls.status !== 'ok') throw new Error('fixtures must draw')
  return [
    renderToStaticMarkup(<WalkForwardView chart={walk} />), renderToStaticMarkup(<IntervalView chart={ci} />),
    renderToStaticMarkup(<DsrView chart={dsr} />), renderToStaticMarkup(<CpcvView chart={cpcv} />),
    renderToStaticMarkup(<NullView tiers={nulls.tiers} skipped={nulls.skipped} />),
  ]
}
const text = (html: string): string => html.replace(/<[^>]+>/g, '\n')

describe('check charts', () => {
  it('print no result word, grade or promise phrase', () => {
    for (const html of views()) expect(text(html).match(BANNED)?.[0]).toBeUndefined()
  })

  it('give every chart a text alternative with the same facts', () => {
    const [walk, ci, dsr, cpcv, nulls] = views()
    expect(walk).toMatch(/role="img" aria-label="Price of the asset from 2020-01-01[^"]*-0\.40/)
    expect(ci).toContain('aria-label="Sharpe 0.50; 95% interval from -0.20 to 1.40; the interval includes zero."')
    expect(dsr).toContain('aria-label="This strategy&#x27;s Sharpe 0.080 against 0.050')
    expect(cpcv).toContain('80% of splits above zero')
    expect(nulls).toContain('random data did as well in 3.0% of draws')
  })

  it('label the bands and the overlap warning on the chart in plain words', () => {
    const [walk, , dsr, cpcv] = views()
    expect(walk).toContain('warm-up window: rules fixed, nothing re-tuned')
    expect(walk).toContain('tested here, not seen before')
    expect(walk).toContain('tuned and tested periods overlap')
    expect(dsr).toContain('best Sharpe expected from luck across 12 counted tests')
    expect(cpcv).toContain('the Sharpe of each split is not stored')
  })

  it('print "not available" with the reason instead of a chart', () => {
    const html = renderToStaticMarkup(<NotAvailable model={{ status: 'not-recorded', reason: 'the fold dates were not recorded for this run' }} />)
    expect(text(html)).toContain('Chart not available: the fold dates were not recorded for this run.')
    expect(html).not.toContain('<svg')
  })
})
