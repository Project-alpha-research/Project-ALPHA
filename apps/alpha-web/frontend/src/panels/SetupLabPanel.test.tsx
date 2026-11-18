import { afterEach, describe, expect, it, vi } from 'vitest'
import * as React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { SetupLabPanel, SetupLabView, type SetupDetail } from './SetupLabPanel'

vi.mock('react', async original => ({ ...await original<typeof import('react')>() }))

const detail: SetupDetail = {
  run: { find_id: 'a'.repeat(16), name: 'Synthetic pullback', description: 'A synthetic pullback after a rise.', recorded_at: '2026-11-01T00:00:00Z', assets: [{ asset: 'SYN', first_bar: '2020-01-01T00:00:00Z', last_bar: '2026-10-31T00:00:00Z' }], labels: ['sheets-truncated'] },
  summary: { totals: { accepted: 1, rejected: 1 } }, spec: null,
  candidates: [{ candidate_id: 1, symbol: 'SYN', status: 'accepted', event_ts: '2026-10-01T00:00:00Z' }, { candidate_id: 2, symbol: 'SYN', status: 'rejected', reason: 'no-trigger' }],
  price_bars: null, price_bars_reason: 'Price bars: not recorded as a setup-run snapshot.', sheets: [], trial_indices: [1],
  studies: [{ run_id: 'b'.repeat(16), rule_version: 'setup-study-2', summary: { occurrences: 1, curve: { mean: [0, -0.02, null], drift: [0, 0.01, null] } }, rows: [], figure: { name: 'event-study.png', png: 'c3ludGhldGlj' }, labels: ['too-few-occurrences'], trial_indices: [2] }],
  trades: [{ run_id: 'c'.repeat(16), rule_version: 'setup-trade-1', summary: { pooled: { trades: 1, mean: -0.02 }, costs: { SYN: { fee_bps: 1, slippage_bps: 2 } } }, rows: [{ asset: 'SYN', entry_ts: '2026-10-02T00:00:00Z', entry_price: 12.5, stop: 12.2, target: 13, exit_price: 12.2, reason: 'stop', net_return: -0.02, complete: true }], figure: { name: 'trades.png', png: null }, labels: ['remeasured-new-cost-rule'], trial_indices: [3] }],
  limits: ['Daily bars only.', 'Sizing, short trades, dividends, funding, portfolios or confirmation on reserved data.'],
  label_explanations: { 'sheets-truncated': 'The sheet cap was reached.', 'too-few-occurrences': 'Too few to judge.', 'remeasured-new-cost-rule': 'An earlier find was measured with a new cost rule; another look.' },
}

function render(value: SetupDetail = detail, selected: string = value.run.find_id): string {
  return renderToStaticMarkup(<SetupLabView list={{ items: [value.run] }} selected={selected} detail={value} error={null} onSelect={() => undefined} />)
}

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe('Setup Lab stored results', () => {
  it('renders every candidate, recorded study figure, controls, trades and costs with labels', () => {
    const html = render()
    for (const text of ['A synthetic pullback after a rise.', 'SYN', 'no-trigger', 'Average path after a match', '1 separate occurrences',
      'Stored baseline', 'Result after costs', '-0.02', '12.5', '12.2', '13', 'stop', 'Cost rule', 'fee bps',
      'What this cannot tell you', 'Daily bars only.', 'The sheet cap was reached.', 'Too few to judge.', 'another look.',
      'Trial indices', 'Price bars: not recorded', 'Total return: not recorded']) expect(html).toContain(text)
    expect(html).toContain('data:image/png;base64,c3ludGhldGlj')
    expect(html).toContain('title="2026-10-01T00:00:00Z"')
    expect(html).toContain('1 Oct 2026, 00:00 UTC')
    expect(html).toContain('color:var(--muted)')
    expect(html).toContain('background:var(--panel)')
    expect(html).not.toContain('NaN')
  })

  it('distinguishes an empty store, no matches, missing candidates, loading and errors', () => {
    const props = { selected: null, detail: null, onSelect: () => undefined }
    expect(renderToStaticMarkup(<SetupLabView {...props} list={{ items: [] }} error={null} />)).toContain('No setup runs')
    expect(render({ ...detail, candidates: [] })).toContain('No matches recorded')
    expect(render({ ...detail, summary: { totals: { accepted: 0 } }, candidates: [detail.candidates![1]] })).toContain('No accepted matches recorded')
    expect(render({ ...detail, candidates: null })).toContain('Matches: not recorded')
    expect(renderToStaticMarkup(<SetupLabView {...props} list={null} error={null} />)).toContain('Loading setup runs')
    const error = renderToStaticMarkup(<SetupLabView {...props} list={null} error="Cannot read stored records" />)
    expect(error).toContain('role="alert"')
    expect(error).not.toContain('No setup runs')
    expect(error).not.toContain('Loading setup runs')
  })

  it('never shows the old detail under a new selection or fills missing values with zero', () => {
    expect(render(detail, 'd'.repeat(16))).not.toContain('12.5')
    expect(render(detail, 'd'.repeat(16))).toContain('Loading selected setup')
    const html = render({ ...detail, studies: [], trades: [], sheets: null })
    expect(html).toContain('Study: not recorded')
    expect(html).toContain('Trades: not recorded')
    expect(html).toContain('Sheets: not recorded')
  })

  it('draws a timeline of stored matches and rounds long decimals for reading', () => {
    const html = render({ ...detail, trades: [{ ...detail.trades[0], rows: [{ asset: 'SYN', candidate_id: 1, complete: true, net_return: -0.0204081632653 }] }] })
    expect(html).toContain('Timeline of stored matches by instrument')
    expect(html).toContain('ringed: a completed trade was recorded')
    expect(html).toContain('-0.0204')
    expect(html).not.toContain('-0.0204081632653')
  })

  it('shows percentages and R for recorded trades and keeps legacy fields unknown', () => {
    const trade = detail.trades[0]
    const html = render({ ...detail, trades: [{ ...trade, rows: [
      { direction: 'short', risk_fraction: 0.05, r_multiple: -1.012, net_return: -0.0506 },
      { net_return: 0.01 },
    ] }] })
    for (const text of ['Initial risk', 'R multiple', '<td>short</td>', '>5.00%</span>',
      '>-5.06%</span>', '<td>-1.01 R</td>', '<td>not recorded</td>']) expect(html).toContain(text)
  })

  it('names the stored risk and short-cost fields in plain words', () => {
    const trade = detail.trades[0]
    const summary = { pooled: { median_r: -1, share_above_zero_r: 0.3, expectancy_r: -0.3 },
      costs: { SYN: { fee_bps: 1, slippage_bps: 2, short_borrow_bps_per_year: 50 } },
      controls: { opposite_direction: { label: 'Opposite direction on the same entries (control only, not counted)' } } }
    const html = render({ ...detail, trades: [{ ...trade, summary }] })
    for (const text of ['Middle return divided by initial stop risk', 'Share of trades above 0 R',
      'Expectancy per trade in R', 'assumed stock borrow, bps per year', 'Opposite direction on the same entries (a control)'])
      expect(html).toContain(text)
  })

  it('keeps repeat labels with their recorded trial index', () => {
    const html = render({ ...detail, trial_labels: { '4': ['repeat'] }, label_explanations: { repeat: 'A repeat, not independent evidence.' } })
    expect(html).toContain('Recorded trial 4')
    expect(html).toContain('A repeat, not independent evidence.')
  })

  it('reads only GET endpoints and discards a disposed detail request', async () => {
    const selected = detail.run.find_id
    let finish: ((value: unknown) => void) | undefined
    const fetcher = vi.fn().mockImplementation((url: string) => url.endsWith(selected)
      ? new Promise(resolve => { finish = resolve })
      : Promise.resolve({ ok: true, json: async () => ({ items: [] }) }))
    vi.stubGlobal('fetch', fetcher)
    const cleanups: (() => void)[] = []
    vi.spyOn(React, 'useEffect').mockImplementation(effect => {
      const cleanup = effect(); if (typeof cleanup === 'function') cleanups.push(cleanup)
    })
    const update = vi.fn()
    vi.spyOn(React, 'useState').mockReturnValueOnce([null, vi.fn()]).mockReturnValueOnce([selected, vi.fn()])
      .mockReturnValueOnce([null, update]).mockReturnValueOnce([null, vi.fn()])
    SetupLabPanel()
    expect(fetcher).toHaveBeenCalledWith(`/api/setup/runs/${selected}`)
    cleanups.forEach(cleanup => cleanup())
    finish?.({ ok: true, json: async () => detail })
    await new Promise(resolve => setTimeout(resolve, 0))
    expect(update).not.toHaveBeenCalled()
  })
})

it('shows the health recorded by each setup run beside its own headline', () => {
  const find = { verdict: 'warn', sentence: 'Data health: warn. The data stops early.' }
  const trade = { verdict: 'fail', sentence: 'Data health: fail. One bar has zero volume.' }
  const value: SetupDetail = {
    ...detail,
    summary: { ...detail.summary, data_health: find },
    studies: detail.studies.map(row => ({ ...row, summary: {
      ...row.summary, data_health: { verdict: 'pass', sentence: 'Data health: pass.' },
    } })),
    trades: detail.trades.map(row => ({ ...row, summary: { ...row.summary, data_health: trade } })),
  }
  const html = render(value)
  expect(html).toContain(`</h2><p>${find.sentence}</p>`)
  expect(html).toContain(`</h3><p>${trade.sentence}</p>`)
  expect(html).not.toContain('<p>Data health: pass.</p>')
  expect(render(detail).match(/<p>Data health: not recorded\.<\/p>/g)).toHaveLength(3)
})
