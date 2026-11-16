import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { RuleTest } from '../api/types'
import { RuleTestReport } from './rundetail/RuleTestReport'
import {
  auditRows,
  benchmarkRows,
  labelChips,
  macroRows,
  macroUnavailable,
  NOT_RECORDED,
  pct,
  ratio,
  testedRows,
  variantRows,
  worstDrawdownLine,
  yearRows,
} from './ruleTestModel'

const performance = (sharpe: number | null, totalReturn: number | null) => ({
  basis: 'full-sample backtest',
  total_return: totalReturn,
  cagr: 0.0913,
  sharpe,
  max_drawdown: -0.3115,
  reasons: (sharpe === null ? { sharpe: 'returns have no variation' } : {}) as Record<string, string>,
})

// Shaped like a stored SPY 50/200 rule test (run 9a99cb94971d54dc), values shortened.
const test: RuleTest = {
  name: 'ma_cross-50-200',
  idea: 'test a 50/200-day moving-average trend rule on SPY and BTC',
  rule_kind: 'ma_cross',
  rule_params: { fast: 50, slow: 200 },
  rule_sentence:
    'Long while the 50-day average is above the 200-day average, otherwise flat; decide at the close, fill at the next open; all capital in, no leverage',
  symbol: 'SPY',
  source: 'alpaca',
  store: 'alpaca',
  labels: ['all-in', 'dev-machine-data', 'quick', 'made-up'],
  test_id: '1a2d962ba3bc8173',
  first_ts: '2016-01-04T00:00:00+00:00',
  last_ts: '2026-11-13T00:00:00+00:00',
  n_bars: 2733,
  fee_bps: 1,
  slippage_bps: 2,
  total_trials: 3,
  diagnostics_reason: null,
  diagnostics: {
    full_sample: { ...performance(0.73, 1.5789), trades: 4, exposure: 0.77 },
    benchmark: {
      ...performance(0.784, 2.7527),
      basis: 'buy and hold, same bars, no costs; close prices',
      strategy_minus_benchmark: {
        total_return: -1.1738,
        cagr: -0.0384,
        sharpe: -0.054,
        max_drawdown: null,
        reasons: { max_drawdown: 'strategy or benchmark metric is unavailable' },
      },
    },
    flags: [{ flag: 'below-benchmark', detail: 'Strategy Sharpe 0.73 is below buy-and-hold Sharpe 0.784.' }],
    audit: [
      { check: 'fills-after-decisions', status: 'PASS', detail: '0 of 9 fills lack a strictly earlier linked decision.' },
      { check: 'enough-trades', status: 'FLAG', detail: '4 closed walk-forward trades; threshold 30.' },
      { check: 'artifacts-intact', status: 'NOT-CHECKED', detail: 'Not verified yet.' },
    ],
    by_year: {
      basis: 'full-sample returns grouped by ending calendar year; partial years included',
      strategy_positive_years: 1,
      benchmark_positive_years: 1,
      years: [
        { year: 2019, strategy_return: 0.1, benchmark_return: 0.2 },
        { year: 2020, strategy_return: -0.05, benchmark_return: null },
      ],
    },
    concentration: { basis: 'closed trades', top_1: 0.48, top_3: 1.12, reasons: {} },
    sensitivity: {
      basis: 'full-sample engine re-runs on the same loaded bars',
      variants: [
        { ...performance(0.728, 1.5718), name: 'costs_x2', kind: 'costs' },
        { ...performance(null, null), name: 'fast=40', kind: 'parameter' },
      ],
    },
    delay: { basis: 'returns-level approximation', base_sharpe: 0.626, delayed_sharpe: 0.622, reasons: {} },
    trials: { basis: 'ledger', total_trials: 3, available_sharpes: 7, dsr: 0.986, reasons: {} },
    worst_drawdown: {
      start: '2020-02-19T00:00:00+00:00',
      trough: '2020-03-23T00:00:00+00:00',
      recovery: '2021-04-05T00:00:00+00:00',
      depth: -0.3115,
      benchmark_return: -0.3418,
      share_explained: 1.097,
      reasons: {},
    },
    macro_window: {
      available: false,
      reason: 'no stored FRED context series',
      basis: null,
      start: null,
      trough: null,
      as_of: null,
      series: [],
    },
    variants_evaluated: 5,
  },
}

const withMacro: RuleTest = {
  ...test,
  diagnostics: {
    ...test.diagnostics!,
    macro_window: {
      available: true,
      reason: null,
      basis: 'stored FRED series as known on the trough date; worst full-sample drawdown',
      start: '2020-02-19',
      trough: '2020-03-23',
      as_of: '2020-03-23',
      series: [
        { series_id: 'VIXCLS', start_value: 14.38, trough_value: 61.59, change: 47.21, reason: null },
        { series_id: 'UNRATE', start_value: null, trough_value: null, change: null, reason: 'no observation known by then' },
      ],
    },
  },
}

describe('rule-test report model', () => {
  it('formats stored values and keeps the stored reason for a missing one', () => {
    expect(pct(1.5789)).toEqual({ text: '157.9%', reason: null, tone: null })
    expect(pct(-0.0384, null, true)).toEqual({ text: '-3.8%', reason: null, tone: 'neg' })
    expect(pct(0, null, true).tone).toBeNull()
    expect(ratio(0.054, null, true)).toEqual({ text: '+0.054', reason: null, tone: 'pos' })
    expect(ratio(null, 'why')).toEqual({ text: NOT_RECORDED, reason: 'why', tone: null })
    expect(ratio(Number.NaN).reason).toBeNull()
  })

  it('says what was tested in the owner’s words with the trial count', () => {
    const rows = Object.fromEntries(testedRows(test).map((row) => [row.label, row.value]))
    expect(rows.Idea).toBe(test.idea)
    expect(rows.Rule).toBe(test.rule_sentence)
    expect(rows.Data).toBe('alpaca · store alpaca')
    expect(rows.Period).toBe('2016-01-04 → 2026-11-13 · 2,733 bars')
    expect(rows.Costs).toBe('fee 1 bps · slippage 2 bps')
    expect(rows.Trials).toBe('3 in the ledger when this ran, this one included · 5 variants also tried')
  })

  it('shows not recorded for what the run did not store', () => {
    const bare: RuleTest = {
      ...test, idea: null, rule_sentence: null, source: null, store: null, first_ts: null,
      fee_bps: null, total_trials: null, diagnostics: null, diagnostics_reason: 'this run recorded no diagnostics.json',
    }
    const rows = Object.fromEntries(testedRows(bare).map((row) => [row.label, row.value]))
    expect(rows.Idea).toBe(NOT_RECORDED)
    expect(rows.Rule).toBe('ma_cross: fast 50, slow 200')
    expect(rows.Data).toBe(NOT_RECORDED)
    expect(rows.Period).toBe(NOT_RECORDED)
    expect(rows.Costs).toBe(`fee ${NOT_RECORDED} · slippage 2 bps`)
    expect(rows.Trials).toBe(NOT_RECORDED)
    expect(auditRows(bare)).toEqual([])
    expect(yearRows(bare)).toEqual([])
    expect(macroRows(bare)).toEqual([])
    expect(worstDrawdownLine(bare)).toBeNull()
    expect(macroUnavailable(bare)).toBe('Not available: this run recorded no diagnostics.json.')
    expect(variantRows(bare)[0].sharpe.text).toBe(NOT_RECORDED)
    expect(benchmarkRows(bare).every((row) => row.difference.text === NOT_RECORDED)).toBe(true)
  })

  it('explains each label and keeps an unknown one as stored', () => {
    const chips = labelChips(test.labels)
    expect(chips.map((chip) => chip.text)).toEqual(test.labels)
    expect(chips[2].title).toContain('Quick mode')
    expect(chips[3].title).toBe('made-up')
    expect(labelChips(null)).toEqual([])
  })

  it('maps audit statuses onto the existing chip tones without a grade', () => {
    expect(auditRows(test).map((row) => [row.check, row.status, row.chip])).toEqual([
      ['fills after decisions', 'PASS', 'pass'],
      ['enough trades', 'FLAG', 'warn'],
      ['artifacts intact', 'NOT-CHECKED', 'kind'],
    ])
  })

  it('relays the stored difference against buy and hold', () => {
    const rows = benchmarkRows(test)
    expect(rows[0]).toMatchObject({
      label: 'Total return',
      strategy: { text: '157.9%' },
      benchmark: { text: '275.3%' },
      difference: { text: '-117.4%', tone: 'neg' },
    })
    expect(rows[3].difference).toEqual({
      text: NOT_RECORDED, reason: 'strategy or benchmark metric is unavailable', tone: null,
    })
  })

  it('lists the variants and the one-bar delay against their own bases', () => {
    const rows = variantRows(test)
    expect(rows.map((row) => row.label)).toEqual(['As tested', 'Costs doubled', 'fast = 40', 'Trade one bar later'])
    expect(rows[1].change.text).toBe('-0.002')
    expect(rows[2].sharpe).toEqual({ text: NOT_RECORDED, reason: 'returns have no variation', tone: null })
    expect(rows[2].change.text).toBe(NOT_RECORDED)
    expect(rows[3].change.text).toBe('-0.004')
    expect(rows[3].note).toContain('0.626')
  })

  it('scales the yearly bars to the largest year and keeps a missing year missing', () => {
    const rows = yearRows(test)
    expect(rows[0]).toMatchObject({ year: 2019, strategy: { text: '+10.0%', tone: 'pos' }, strategyBar: 0.5, benchmarkBar: 1 })
    expect(rows[1]).toMatchObject({ strategy: { text: '-5.0%', tone: 'neg' }, benchmark: { text: NOT_RECORDED }, benchmarkBar: 0 })
  })

  it('gives the stored reason when the macro window is unavailable, the series when it is', () => {
    expect(macroUnavailable(test)).toBe('Not available: no stored FRED context series.')
    expect(worstDrawdownLine(test)).toBe('2020-02-19 → 2020-03-23 · strategy -31.1% · buy and hold -34.2%')
    expect(macroUnavailable(withMacro)).toBeNull()
    expect(macroRows(withMacro)).toEqual([
      { series: 'VIXCLS', start: { text: '14.38', reason: null, tone: null }, trough: { text: '61.59', reason: null, tone: null }, change: { text: '+47.21', reason: null, tone: null } },
      {
        series: 'UNRATE',
        start: { text: NOT_RECORDED, reason: 'no observation known by then', tone: null },
        trough: { text: NOT_RECORDED, reason: 'no observation known by then', tone: null },
        change: { text: NOT_RECORDED, reason: 'no observation known by then', tone: null },
      },
    ])
  })
})

describe('rule-test report section', () => {
  it('renders every heading, the stored sentences and the audit statuses', () => {
    const html = renderToStaticMarkup(createElement(RuleTestReport, { test }))
    for (const heading of [
      'What was tested', 'Worth a look', 'Audit', 'Against buy and hold',
      'If things were slightly different', 'By year', 'Macro during the worst drawdown',
    ]) expect(html).toContain(`<caption>${heading}</caption>`)
    expect(html).toContain('Long while the 50-day average is above the 200-day average')
    expect(html).toContain('Strategy Sharpe 0.73 is below buy-and-hold Sharpe 0.784.')
    expect(html).toContain('<span class="chip warn">FLAG</span>')
    expect(html).toContain('<span class="chip kind">NOT-CHECKED</span>')
    expect(html).toContain('Not available: no stored FRED context series.')
    expect(html).toContain('title="strategy or benchmark metric is unavailable"')
    expect(html).not.toContain('LEGACY_CONTEXT_UNKNOWN')
    // stored basis notes read as sentences; their words are relayed unchanged
    expect(html).toContain('Full-sample engine re-runs on the same loaded bars.')
    expect(html).toContain('Full-sample returns grouped by ending calendar year; partial years included')
  })

  it('renders the macro table when the window is stored', () => {
    const html = renderToStaticMarkup(createElement(RuleTestReport, { test: withMacro }))
    expect(html).toContain('VIXCLS')
    expect(html).toContain('+47.21')
    expect(html).toContain('no observation known by then')
  })

  it('renders a run without diagnostics as one plain line, not an error', () => {
    const bare: RuleTest = { ...test, diagnostics: null, diagnostics_reason: 'this run recorded no diagnostics.json' }
    const html = renderToStaticMarkup(createElement(RuleTestReport, { test: bare }))
    expect(html).toContain('Diagnostics not recorded: this run recorded no diagnostics.json.')
    expect(html).not.toContain('<caption>Audit</caption>')
  })
})
