import { describe, expect, it } from 'vitest'
import {
  filterChoices, filterRuns, formatDay, formatSharpe, nextSort, NO_FILTER, plainError, sortRuns, sparkPath, type RecentRun,
} from './recentTestsModel'

function run(id: string, extra: Partial<RecentRun> = {}): RecentRun {
  return {
    run_id: id.padEnd(16, '0'), kind: 'runs', mtime: 1, display_name: `run ${id}`, symbol: 'SPY', idea: `idea ${id}`, rule_name: null,
    first_ts: null, last_ts: null, trades: 10, tries: 3, oos_sharpe: 0.1, evidence: 'some evidence', spark: [], ...extra,
  }
}

describe('recent tests table', () => {
  const rows = [run('a', { oos_sharpe: 0.5, symbol: 'QQQ' }), run('b', { oos_sharpe: null }), run('c', { oos_sharpe: -0.1, evidence: null })]
  it('sorts both ways with missing values last', () => {
    expect(sortRuns(rows, { key: 'oos_sharpe', descending: true }).map(r => r.run_id[0])).toEqual(['a', 'c', 'b'])
    expect(sortRuns(rows, { key: 'oos_sharpe', descending: false }).map(r => r.run_id[0])).toEqual(['c', 'a', 'b'])
    expect(sortRuns(rows, { key: 'idea', descending: false }).map(r => r.run_id[0])).toEqual(['a', 'b', 'c'])
    expect(sortRuns(rows, { key: 'symbol', descending: true }).map(r => r.run_id[0])).toEqual(['b', 'c', 'a'])
    expect(sortRuns(rows, { key: 'evidence', descending: false }).map(r => r.run_id[0])).toEqual(['a', 'b', 'c'])
  })
  it('flips the direction on the same column and picks a first direction', () => {
    expect(nextSort({ key: 'mtime', descending: true }, 'mtime')).toEqual({ key: 'mtime', descending: false })
    expect(nextSort({ key: 'mtime', descending: true }, 'symbol')).toEqual({ key: 'symbol', descending: false })
    expect(nextSort({ key: 'symbol', descending: true }, 'trades')).toEqual({ key: 'trades', descending: true })
  })
  it('filters by asset, idea and reading and lists the choices', () => {
    expect(filterRuns(rows, NO_FILTER)).toHaveLength(3)
    expect(filterRuns(rows, { ...NO_FILTER, asset: 'QQQ' }).map(r => r.run_id[0])).toEqual(['a'])
    expect(filterRuns(rows, { ...NO_FILTER, idea: 'idea b' }).map(r => r.run_id[0])).toEqual(['b'])
    expect(filterRuns(rows, { ...NO_FILTER, reading: 'some evidence' })).toHaveLength(2)
    expect(filterChoices(rows)).toEqual({ assets: ['QQQ', 'SPY'], ideas: ['idea a', 'idea b', 'idea c'], readings: ['some evidence'] })
    expect(filterChoices([run('d', { idea: null, rule_name: 'rsi' })]).ideas).toEqual(['rsi'])
  })
  it('formats numbers, dates and the sparkline', () => {
    expect([formatSharpe(null), formatSharpe(0.1349)]).toEqual(['—', '0.13'])
    expect(formatDay(Date.UTC(2026, 10, 22) / 1000)).toBe('22 Nov 2026')
    expect(sparkPath([1], 10, 10)).toBe('')
    expect(sparkPath([0, 1], 10, 10, 0)).toBe('M0.0 10.0 L10.0 0.0')
    expect(sparkPath([2, 2, 2], 10, 10, 0)).toContain('M0.0')
  })
  it('says what failed without a status code or request id', () => {
    expect(plainError(new Error('500 Internal Server Error — No such run. [request abc]'), 'the tests'))
      .toBe('Could not load the tests. No such run. Check that the Workstation server is running, then reload the page.')
    expect(plainError(new TypeError('Failed to fetch'), 'the tests')).toContain('The server did not answer.')
  })
})
