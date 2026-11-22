import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { MlStoredRun } from '../api/types'
import { MachineLearningView } from './MachineLearning'

const run: MlStoredRun = {
  run_id: 'a'.repeat(16), mtime: 1, assets: ['SPY', 'QQQ'], model: 'Qlib worker; the model type is not recorded in the run',
  costs: '1 bp fee and 2 bp slippage per trade', split_sentence: 'The model was refit 1 times, each on days before its own test days.',
  n_oos_periods: 63, label: null, survivorship_warning: 'Assets chosen from today\'s members can flatter the past.',
  metrics: { total_return: 0.05, benchmark_total_return: 0.02, max_drawdown: -0.03, sharpe: null, cagr: null, mean_turnover: null, total_fees: null, total_slippage_cost: null, sharpe_reason: 'Fewer than two scored periods.' },
  folds_total: 1,
  folds: [{ fold: 0, train_start: '2020-01-01', train_end: '2020-02-20', test_start: '2020-03-02', test_end: '2020-03-31' }],
}

describe('machine learning run view', () => {
  it('shows the split sentence, assets, model, costs, reading and the fold table', () => {
    const html = renderToStaticMarkup(<MachineLearningView run={run} />)
    expect(html).toContain('each on days before its own test days')
    expect(html).toContain('SPY, QQQ')
    expect(html).toContain('Qlib worker; the model type')
    expect(html).toContain('1 bp fee and 2 bp slippage per trade')
    expect(html).toContain('ahead of +2.0% for an equal-weight mix of the same assets, rebalanced each tested period and without costs')
    expect(html).toContain('Sharpe: not worked out. Fewer than two scored periods.')
    expect(html).toContain('Assets chosen from today&#x27;s members can flatter the past.')
    expect(html).toContain('<th scope="col">Tested on</th>')
    expect(html).toContain('2020-03-02 to 2020-03-31')
  })
})
