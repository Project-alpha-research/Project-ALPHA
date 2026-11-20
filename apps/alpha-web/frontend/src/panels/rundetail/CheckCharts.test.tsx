import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { NullTiers } from '../../api/types'
import type { ValidateManifest } from '../../explain/types'
import { BANNED } from '../__fixtures__/scanWords'
import { NotAvailable } from './chartParts'
import { CpcvView, DsrView, IntervalView } from './CheckCharts'
import { ciChart, cpcvChart, dsrChart, type PriceBar } from './checkChartModel'
import { nullCharts } from './nullChartModel'
import { NullView } from './NullChart'
import { WalkForwardView } from './WalkForward'
import { walkForwardChart } from './walkForwardModel'

const DAY = 86_400
const T0 = Date.parse('2020-01-01T00:00:00Z') / 1000
const iso = (day: number) => new Date((T0 + day * DAY) * 1000).toISOString()
const fold = (index: number, a: number, b: number, c: number, d: number, sharpe: number | null) =>
  ({ index, n_test: d - c, oos_sharpe: sharpe, train_start_ts: iso(a), train_end_ts: iso(b), test_start_ts: iso(c), test_end_ts: iso(d) })
const manifest = {
  oos_semantics: 'fixed_rule_evaluation_no_refit',
  metadata: { symbol: 'AAPL', periods_per_year: 252 },
  folds: [fold(0, 0, 120, 105, 200, 1.5), fold(1, 100, 200, 205, 300, -0.4)],
  cis: [{ metric: 'sharpe', confidence: 0.95, point: 0.5, lower: -0.2, upper: 1.4 }],
  dsr: { sharpe: 0.08, psr: 0.9, dsr: 0.9123, expected_max_sharpe: 0.05, n_trials: 12, threshold: 0.95, passed: false },
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
    expect(walk).toMatch(/role="group" aria-label="Price of the asset from 2020-01-01[^"]*-0\.40/)
    expect(ci).toContain('aria-label="Sharpe 0.50; 95% interval from -0.20 to 1.40; the interval includes zero."')
    expect(dsr).toContain('aria-label="This strategy&#x27;s Sharpe 0.080 per trading period, 1.27 per year, against 0.050')
    expect(cpcv).toContain('80% of splits above zero')
    expect(nulls).toContain('random data did as well in 3.0% of draws')
  })

  it('label the bands and the overlap warning on the chart in plain words', () => {
    const [walk, , dsr, cpcv] = views()
    expect(walk).toContain('warm-up: rules fixed, nothing re-tuned')
    expect(walk).toContain('tested here, not seen before')
    expect(walk).toContain('tuned and tested periods overlap')
    expect(walk).toContain('The rules never change in this test.')
    expect(walk).toContain('line: price from the bars stored now; the run’s own bars were not saved with it')
    expect(walk).toContain('unshaded price: before the first test')
    expect(dsr).toContain('best Sharpe expected from luck across 12 counted tests')
    expect(dsr).toContain('The deflated Sharpe (0.912) is a probability from 0 to 1, not a Sharpe ratio.')
    expect(dsr).toContain('per trading period')
    expect(cpcv).toContain('bar: mean ± one standard deviation')
    expect(cpcv).toContain('the Sharpe of each split is not stored')
  })

  it('print "not available" with the reason instead of a chart', () => {
    const html = renderToStaticMarkup(<NotAvailable model={{ status: 'not-recorded', reason: 'the fold dates were not recorded for this run' }} />)
    expect(text(html)).toContain('Chart not available: the fold dates were not recorded for this run.')
    expect(html).not.toContain('<svg')
  })

  it('print the Sharpe inside each tested band and the fold number on each staircase row', () => {
    const [walk] = views()
    expect(walk).toContain('>Sharpe 1.5<')
    expect(walk).toContain('>Sharpe -0.4<')
    expect(walk).toContain('before the first test')
    expect(walk.match(/class="cc-stair-test/g)).toHaveLength(2)
    expect(walk).not.toContain('show all folds')
  })

  it('collapse a long staircase to the first 3 and last 2 rows, keep every band, and offer all folds', () => {
    const many = { ...manifest, folds: Array.from({ length: 20 }, (_, i) => fold(i, i * 10, i * 10 + 20, i * 10 + 21, i * 10 + 30, i / 10)) } as unknown as ValidateManifest
    const chart = walkForwardChart(many, null)
    if (chart.status !== 'ok') throw new Error('fixture must draw')
    const html = renderToStaticMarkup(<WalkForwardView chart={chart} />)
    expect(html.match(/class="cc-stair-test/g)).toHaveLength(5)
    expect(html.match(/class="cc-fold"/g)).toHaveLength(20)
    expect(html).toContain('\u2026 20 folds in total')
    expect(html).toContain('show all folds')
    expect(html).toContain('Price not available: no stored bars for AAPL.')
    const open = renderToStaticMarkup(<WalkForwardView chart={chart} initialExpanded />)
    expect(open.match(/class="cc-stair-test/g)).toHaveLength(20)
    expect(open).toContain('show fewer folds')
    expect(open).not.toContain('folds in total')
  })

  it('draw a tier with few draws as ticks and say it is a rough picture', () => {
    const few = nullCharts(manifest, { tiers: [{ tier: 'returns_level', statistics: [-0.2, 0.1, 0.4, 0.5] }] })
    if (few.status !== 'ok') throw new Error('fixture must draw')
    const html = renderToStaticMarkup(<NullView tiers={few.tiers} skipped={few.skipped} />)
    expect(html.match(/class="cc-tick"/g)).toHaveLength(4)
    expect(html).not.toContain('cc-hist')
    expect(html).toContain('only 4 random series: a rough picture')
    expect(html).toContain('quick version')
  })
})
