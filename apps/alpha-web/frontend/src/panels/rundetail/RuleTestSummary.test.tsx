import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { FigureCatalogueItem, RuleTest } from '../../api/types'
import { RuleTestReport } from './RuleTestReport'

const performance = { basis: 'full history', total_return: 0.125, sharpe: 0.75, cagr: 0.06, max_drawdown: -0.14, reasons: {} }
const test: RuleTest = {
  idea: 'Buy after a breakout', rule_sentence: 'Hold after a new high', rule_kind: 'breakout', rule_params: {},
  symbol: 'TEST', first_ts: '2020-01-01', last_ts: '2021-12-31', name: null, store: null, source: null,
  labels: ['exploratory', 'dev-machine-data', 'short-history', 'quick', 'too-few-trades'],
  test_id: null, n_bars: null, fee_bps: null, slippage_bps: null, total_trials: null, diagnostics_reason: null,
  diagnostics: {
    full_sample: { ...performance, trades: 35, exposure: null },
    benchmark: { ...performance, total_return: 0.2, sharpe: 1.2, strategy_minus_benchmark: null },
    flags: [{ flag: 'below-benchmark', detail: 'The stored comparison.' }],
    audit: [{ check: 'fills-inside-bar-range', status: 'PASS', detail: 'All prices matched.' }],
    by_year: null, concentration: null, sensitivity: null, delay: null, trials: null,
    worst_drawdown: null, macro_window: null, variants_evaluated: null,
  },
}
const manifest = { n_trades: 4, verdict: { edge: 'B', robustness: 'B', risk: 'B', sample: 'B', overall: 'C', detail: {} } }
const render = (run = test, figures: FigureCatalogueItem[] = []) =>
  renderToStaticMarkup(<RuleTestReport test={run} manifest={manifest} runId="fixture" figures={figures} />)
const tile = (html: string, label: string) => {
  const match = html.split('<div class="metric">').slice(1).map(part => part.split('</div>')[0])
    .find(part => part.includes('>' + label + '<'))
  expect(match, label).toBeDefined()
  return match!
}

describe('rule-test Summary', () => {
  it('opens with the owner’s idea, market, dates and both stored returns', () => {
    expect(render()).toMatch(/<h2[^>]*>[^<]*Buy after a breakout[^<]*TEST[^<]*2020-01-01[^<]*2021-12-31[^<]*12\.5%[^<]*20\.0%[^<]*<\/h2>/)
  })

  it('uses the plain rule when the idea is absent and explains the missing idea in the disclosure', () => {
    const html = render({ ...test, idea: null })
    expect(html).toMatch(/<h2[^>]*>[^<]*Hold after a new high/)
    expect(html).toContain('<small>no idea text was saved with this run</small>')
  })

  it('puts caveats below their values and distinguishes the grade sample from the full history', () => {
    const html = render()
    expect(tile(html, 'Total return after costs')).toMatch(/12\.5%.*[Ee]xploratory/)
    expect(tile(html, 'Return per year')).toMatch(/6\.0%.*three years/)
    expect(tile(html, 'Worst drop')).toMatch(/-14\.0%.*three years/)
    expect(tile(html, 'Closed trades')).toMatch(/35.*walk-forward.*dimensions alone would give B.*held at C.*only 4 closed trades/)
    expect(tile(html, 'Buy-and-hold return')).toMatch(/20\.0%.*development machine/)
    expect(html).toMatch(/Risk-adjusted score \(Sharpe\).*0\.750.*1\.200.*Quick mode/)
  })

  it('adapts to missing facts without inventing a comparison or a chart', () => {
    const html = render({ ...test, idea: null, rule_sentence: null, symbol: null, diagnostics: null })
    const headline = html.match(/<h2[^>]*>(.*?)<\/h2>/)?.[1]
    expect(headline).toContain('no return comparison')
    expect(headline).not.toContain('not recorded')
    for (const label of ['Total return after costs', 'Return per year', 'Worst drop', 'Closed trades', 'Buy-and-hold return']) {
      expect(tile(html, label)).toContain('not recorded')
    }
    expect(html).toContain('no chart stored for this run')
  })

  it('keeps the flag and variants above the two closed disclosures', () => {
    const html = render()
    const sections = ['no chart stored for this run', 'Worth a look', 'If things were slightly different',
      '<details><summary>What was tested</summary>', '<details><summary>Checks on the test itself</summary>']
    const positions = sections.map(text => html.indexOf(text))
    expect(positions.every(position => position >= 0)).toBe(true)
    expect(positions).toEqual([...positions].sort((a, b) => a - b))
    expect(html).toContain('Were trade prices within the market range?')
    expect(html).toContain('fills-inside-bar-range')
    expect(html).toContain('All prices matched.')
  })

  it('uses the available comparison and drawdown figure cards', () => {
    const figures = ['unrelated', 'equity_underwater', 'equity_vs_passive'].map(figure_id => ({
      figure_id, title: figure_id, summary: '', section: 'risk', panel_count: 2, available: true, unavailable_reason: null,
    }))
    const html = render(test, figures)
    expect(html).toContain('<h3>equity_vs_passive</h3>')
    expect(html).toContain('<h3>equity_underwater</h3>')
    expect(html).not.toContain('unrelated')
    expect(html).not.toContain('no chart stored')
  })
})
