import { describe, expect, it } from 'vitest'
import type { MlStoredRun } from '../api/types'
import { EMPTY_STATE_TEXT, FIRST_RUN_COMMAND, foldRows, fraction, readingWords } from './mlRunsModel'

function run(extra: Partial<MlStoredRun['metrics']> = {}): MlStoredRun {
  return {
    run_id: 'a'.repeat(16), mtime: 1, assets: ['SPY', 'QQQ', 'IWM', 'TLT', 'GLD'], model: 'Qlib worker; the model type is not recorded in the run',
    costs: '1 bp fee and 2 bp slippage per trade', split_sentence: 'The model was refit 3 times.', n_oos_periods: 126,
    label: 'OOS replay validated — model not recomputed under counterfactual',
    metrics: {
      total_return: 0.085, benchmark_total_return: 0.12, max_drawdown: -0.07, sharpe: 0.8, cagr: 0.04, mean_turnover: 0.3,
      total_fees: 1, total_slippage_cost: 2, sharpe_reason: null, ...extra,
    },
    folds_total: 1,
  folds: [{ fold: 0, train_start: '2020-01-01', train_end: '2020-02-20', test_start: '2020-03-02', test_end: '2020-03-31' }],
  }
}

describe('machine learning window words', () => {
  it('reads the stored numbers after costs without a verdict', () => {
    const words = readingWords(run()).join(' ')
    expect(words).toContain('returned +8.5%, behind +12.0% for holding the same assets')
    expect(words).toContain('Largest fall from a peak: -7.0%')
    expect(words).toContain('Sharpe after costs: 0.80')
    expect(words).not.toMatch(/pass|fail|buy|sell|profit/i)
  })

  it('says a missing number is missing, with its reason, and never zero', () => {
    const words = readingWords(run({ sharpe: null, sharpe_reason: 'Fewer than two scored periods.', benchmark_total_return: null })).join(' ')
    expect(words).toContain('Sharpe: not worked out. Fewer than two scored periods.')
    expect(words).toContain('Holding the same assets: not recorded.')
    expect(fraction(null)).toBe('not recorded')
    expect(fraction(0)).toBe('0.0%')
  })

  it('lays the fold table out as readable days', () => {
    expect(foldRows(run().folds)).toEqual([{ fold: 0, trained: '2020-01-01 to 2020-02-20', tested: '2020-03-02 to 2020-03-31' }])
  })

  it('tells how to make the first run, and does not start one', () => {
    expect(EMPTY_STATE_TEXT).toContain('ask your AI')
    expect(FIRST_RUN_COMMAND).toBe('alpha ml run research/examples/ml-gbm-etfs.toml')
  })
})
