import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { RuleTest } from '../api/types'
import { RuleTestReport } from './rundetail/RuleTestReport'
import {
  auditRows,
  summaryHeadline,
  summaryNumbers,
  labelChips,
  ruleWords,
  NOT_RECORDED,
  pct,
  ratio,
  testedRows,
  variantRows,
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

// Supply explicitly recorded period facts to the period-specific presentation tests.
const period = (run: RuleTest) => ({
  first_ts: '2017-02-01', last_ts: '2019-07-01', price_basis: 'with dividends',
  strategy: run.diagnostics?.full_sample, benchmark: run.diagnostics?.benchmark,
  relative_return: run.diagnostics?.benchmark?.strategy_minus_benchmark?.total_return,
})

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
    expect(rows.Idea).toBe('no idea text was saved with this run')
    expect(rows.Rule).toBe('ma_cross: fast 50, slow 200')
    expect(rows.Data).toBe(NOT_RECORDED)
    expect(rows.Period).toBe(NOT_RECORDED)
    expect(rows.Costs).toBe(`fee ${NOT_RECORDED} · slippage 2 bps`)
    expect(rows.Trials).toBe(NOT_RECORDED)
    expect(auditRows(bare)).toEqual([])
    expect(variantRows(bare)[0].sharpe.text).toBe(NOT_RECORDED)
    expect(summaryNumbers(bare, {}).every(row => row.value.text === NOT_RECORDED)).toBe(true)
  })

  it('explains each label and keeps an unknown one as stored', () => {
    const chips = labelChips(test.labels)
    expect(chips.map((chip) => chip.text)).toEqual(test.labels)
    expect(chips[2].title).toContain('Quick mode')
    expect(chips[3].title).toContain('No explanation was saved')
    expect(labelChips(null)).toEqual([])
  })

  it('maps audit statuses onto the existing chip tones without a grade', () => {
    expect(auditRows(test).map((row) => [row.id, row.check, row.status, row.chip])).toEqual([
      ['fills-after-decisions', 'Did each trade follow its decision?', 'sound', 'pass'],
      ['enough-trades', 'Were there enough closed trades?', 'flag', 'warn'],
      ['artifacts-intact', 'Were the saved files verified as unchanged?', 'not checked', 'kind'],
    ])
  })

  it.each([
    [0.5, 0.3, 'ahead of'], [0.1, -0.1, 'behind'], [0.2, 0, 'level with'], [0.5, null, 'compared with'],
  ] as const)('describes the recorded comparison for return %s and difference %s', (ruleReturn, difference, wording) => {
    const diagnostics = test.diagnostics!
    const benchmark = diagnostics.benchmark!
    const run = { ...test, diagnostics: { ...diagnostics,
      full_sample: { ...diagnostics.full_sample!, total_return: ruleReturn },
      benchmark: { ...benchmark, total_return: 0.2,
        strategy_minus_benchmark: { ...benchmark.strategy_minus_benchmark!, total_return: difference } },
    } }
    expect(summaryHeadline(run, period(run))).toContain(`${wording} 20.0% for simply holding the market`)
  })

  it('uses only the available side of a comparison, including a zero', () => {
    const diagnostics = test.diagnostics!
    const ruleOnly = { ...test, diagnostics: { ...diagnostics, benchmark: null,
      full_sample: { ...diagnostics.full_sample!, total_return: 0 } } }
    expect(summaryHeadline(ruleOnly, period(ruleOnly))).toContain('returned 0.0% after costs')
    expect(summaryHeadline(ruleOnly, period(ruleOnly))).toContain('buy-and-hold return is unavailable')
    const holdOnly = { ...test, diagnostics: { ...diagnostics, full_sample: null } }
    expect(summaryHeadline(holdOnly, period(holdOnly))).toContain('holding the market returned 275.3%')
    expect(summaryHeadline(holdOnly, period(holdOnly))).not.toContain('157.9%')
  })

  it('keeps a recorded exploratory watermark with the rule return', () => {
    const watermark = 'EXPLORATORY / RESEARCH GATE NOT COMPLETED'
    expect(summaryNumbers(test, {}, watermark)[0].caveats).toContain(watermark)
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

  it('keeps a missing number and its stored reason together', () => {
    const diagnostics = test.diagnostics!
    const sparse = { ...test, diagnostics: { ...diagnostics, full_sample: {
      ...diagnostics.full_sample!, cagr: null, reasons: { cagr: 'too short to annualize' },
    } } }
    expect(summaryNumbers(sparse, { spine: { periods: { tradable: period(sparse) } } })[1].value).toEqual({
      text: NOT_RECORDED, reason: 'too short to annualize', tone: null,
    })
  })
})

describe('rule-test report section', () => {
  it('keeps the test setup, flag detail, audit statuses and variant basis', () => {
    const html = renderToStaticMarkup(createElement(RuleTestReport, { test, runId: 'fixture', manifest: {}, figures: [] }))
    expect(html).toContain('Long while the 50-day average is above the 200-day average')
    expect(html).toContain('Strategy Sharpe 0.73 is below buy-and-hold Sharpe 0.784.')
    expect(html).toContain('<span class="chip warn">flag</span>')
    expect(html).toContain('<span class="chip kind">not checked</span>')
    expect(html).not.toContain('LEGACY_CONTEXT_UNKNOWN')
    expect(html).toContain('Full-sample engine re-runs on the same loaded bars.')
  })

  it('renders the stored reason when the run has no diagnostics', () => {
    const bare = { ...test, diagnostics: null, diagnostics_reason: 'this run recorded no diagnostics.json' }
    const html = renderToStaticMarkup(createElement(RuleTestReport, { test: bare, runId: 'fixture', manifest: {}, figures: [] }))
    expect(html).toContain('this run recorded no diagnostics.json')
    expect(html).not.toContain('<caption>Audit</caption>')
  })
})

it('keeps legacy data dates separate from the unrecorded tradable and scored rows', () => {
  const html = renderToStaticMarkup(createElement(RuleTestReport, { test, manifest: {}, runId: 'old', figures: [] }))
  expect(html).toContain('could trade from not recorded')
  expect(html).toContain('data from 2016-01-04 to 2026-11-13')
  expect(html).toContain('Scored test periods only')
})

it('keeps the original recorded full-history comparison accessible on an older run', () => {
  const html = renderToStaticMarkup(createElement(RuleTestReport, { test, manifest: {}, runId: 'older', figures: [] }))
  const legacy = html.split('<summary>Recorded full history</summary>')[1]
  expect(legacy).toContain('157.9%')
  expect(legacy).toContain('275.3%')
})

it('explains each stored data health label and shows the saved finding by the headline', () => {
  for (const status of ['pass', 'warn', 'fail', 'unchecked', 'overridden']) {
    expect(labelChips([`data-health-${status}`])[0].title).not.toContain('No explanation')
  }
  const sentence = 'Data health: warn. The data stops early.'
  const html = renderToStaticMarkup(createElement(RuleTestReport, {
    test, manifest: { data_health: { verdict: 'warn', sentence } }, runId: 'a', figures: null,
  }))
  expect(html).toContain(sentence)
})

const OWNER: RuleTest = {
  ...test, rule_kind: 'owner', rule_params: {}, rule_family: 'owner:0123456789ab', labels: ['null-closes-for-high-low'],
  rule_sentence: 'Buy at the next open when the 14-day ATR is below the 50-day ATR. Sell at the next open when that stops being true. Long or flat.',
}

describe('ruleWords', () => {
  it('states an owner rule with its family', () => {
    expect(ruleWords(OWNER)).toEqual({ sentence: OWNER.rule_sentence, family: 'owner:0123456789ab' })
  })

  it('says so when an owner run has no stored rule', () => {
    expect(ruleWords({ ...OWNER, rule_sentence: null, rule_family: null }))
      .toEqual({ sentence: 'the rule was not stored with this run', family: null })
  })

  it('says so when a run has no rule kind at all', () => {
    expect(ruleWords({ ...test, rule_kind: null, rule_sentence: null }))
      .toEqual({ sentence: 'the rule was not stored with this run', family: null })
  })

  it('leaves the three old kinds on their present wording', () => {
    expect(ruleWords(test)).toBeNull()
    expect(testedRows(test).find((row) => row.label === 'Rule')?.value).toBe(test.rule_sentence)
  })

  it('shows the owner sentence in the tested rows and gives the new label a plain meaning', () => {
    expect(testedRows(OWNER).find((row) => row.label === 'Rule')?.value).toBe(OWNER.rule_sentence)
    const [chip] = labelChips(['null-closes-for-high-low'])
    expect(chip.title).toMatch(/closes for high and low/)
    expect(chip.title).not.toMatch(/No explanation/)
  })
})
