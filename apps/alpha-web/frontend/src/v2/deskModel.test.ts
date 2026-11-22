import { describe, expect, it } from 'vitest'
import {
  filterChoices, filterRuns, formatNumber, isLegacyHash, matchSymbols, nextSort, NO_FILTER, parseRoute, plainError,
  routeHash, signTone, sortRuns, sparkPath, sparkTone, statusDot, stepIndex, type DeskRun, type DeskStatus,
} from './deskModel'

function run(id: string, extra: Partial<DeskRun> = {}): DeskRun {
  return {
    run_id: id.padEnd(16, '0'), kind: 'runs', mtime: 1, display_name: `run ${id}`, symbol: 'SPY', idea: `idea ${id}`, rule_name: null,
    first_ts: null, last_ts: null, trades: 10, tries: 3, oos_sharpe: 0.1, evidence: 'some evidence', spark: [], ...extra,
  }
}

describe('desk routes', () => {
  it('keeps the old shell URLs on the old shell', () => {
    expect(isLegacyHash('#legacy')).toBe(true)
    expect(isLegacyHash('#page=results&pane=RunDetail')).toBe(true)
    expect(isLegacyHash('#place=tests')).toBe(false)
    expect(isLegacyHash('')).toBe(false)
  })
  it('round-trips a place, a run and a symbol', () => {
    const hash = routeHash({ place: 'tests', run: '0859801ce8721413' })
    expect(parseRoute(hash)).toEqual({ place: 'tests', run: '0859801ce8721413', symbol: null })
    expect(parseRoute(routeHash({ place: 'charts', symbol: 'BTC/USDT' })).symbol).toBe('BTC/USDT')
  })
  it('falls back to Home and drops a malformed run id', () => {
    expect(parseRoute('#place=nowhere&run=xyz')).toEqual({ place: 'home', run: null, symbol: null })
  })
})

describe('plain errors', () => {
  it('drops the status code and request id but keeps the server words', () => {
    const text = plainError(new Error('500 Internal Server Error — No such run. [request abc]'), 'the run')
    expect(text).toBe('Could not load the run. No such run. Check that the Workstation server is running, then reload the page.')
  })
  it('says the server did not answer for a network failure', () => {
    expect(plainError(new TypeError('Failed to fetch'), 'tests')).toContain('The server did not answer.')
    expect(plainError('500 — The Workstation request failed.', 'tests')).toContain('The server did not answer.')
  })
})

describe('numbers and sparkline', () => {
  it('formats a missing number as a dash and gives a sign tone', () => {
    expect(formatNumber(null)).toBe('—')
    expect(formatNumber(0.1349)).toBe('0.13')
    expect([signTone(0.2), signTone(-1), signTone(0), signTone(null)]).toEqual(['up', 'down', '', ''])
  })
  it('scales a path to the box and draws nothing for one point', () => {
    expect(sparkPath([1], 10, 10)).toBe('')
    expect(sparkPath([0, 1], 10, 10, 0)).toBe('M0.0 10.0 L10.0 0.0')
    expect(sparkPath([2, 2, 2], 10, 10, 0)).toContain('M0.0')
    expect([sparkTone([1, 2]), sparkTone([2, 1]), sparkTone([])]).toEqual(['up', 'down', ''])
  })
})

describe('runs table', () => {
  const rows = [run('a', { oos_sharpe: 0.5, symbol: 'QQQ' }), run('b', { oos_sharpe: null }), run('c', { oos_sharpe: -0.1, evidence: null })]
  it('sorts both ways with missing values last', () => {
    expect(sortRuns(rows, { key: 'oos_sharpe', descending: true }).map(r => r.run_id[0])).toEqual(['a', 'c', 'b'])
    expect(sortRuns(rows, { key: 'oos_sharpe', descending: false }).map(r => r.run_id[0])).toEqual(['c', 'a', 'b'])
    expect(sortRuns(rows, { key: 'idea', descending: false }).map(r => r.run_id[0])).toEqual(['a', 'b', 'c'])
    expect(sortRuns(rows, { key: 'evidence', descending: false }).map(r => r.run_id[0])).toEqual(['a', 'b', 'c'])
  })
  it('flips the direction on the same column and picks a sensible first direction', () => {
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
})

describe('status dot', () => {
  const night = { date: '2026-11-20', run_number: 2, complete: 'all three paths', blocking: 0, minor: 0, ready: false, reasons: [] }
  const status = (nightly: DeskStatus['nightly'], problem: string | null = null): DeskStatus => ({ reserved_start: '2024-01-01', nightly, nightly_problem: problem })
  it('shows nothing without an answer', () => {
    expect(statusDot(null)).toBeNull()
    expect(statusDot(status(null))).toBeNull()
  })
  it('names the last nightly run and its problems', () => {
    expect(statusDot(status(night))).toEqual({ tone: 'ok', text: 'Last nightly run 2026-11-20 (#2): all three paths. No problems.' })
    expect(statusDot(status({ ...night, blocking: 1 }))?.tone).toBe('bad')
    expect(statusDot(status({ ...night, minor: 2 }))?.text).toContain('2 minor problems')
    expect(statusDot(status(null, 'no records'))?.tone).toBe('warn')
  })
})

describe('small helpers', () => {
  it('wraps the gallery index', () => {
    expect([stepIndex(0, -1, 3), stepIndex(2, 1, 3), stepIndex(0, 1, 0)]).toEqual([2, 0, 0])
  })
  it('matches symbols by prefix first', () => {
    expect(matchSymbols(['SPY', 'QQQ', 'BTC/USDT', 'ETH/USDT'], 'zz')).toEqual([])
    expect(matchSymbols(['SPY', 'QQQ', 'BTC/USDT', 'ETH/USDT'], 'usd')).toEqual(['BTC/USDT', 'ETH/USDT'])
    expect(matchSymbols(['SPY', 'SPX', 'ASP'], 'sp')).toEqual(['SPY', 'SPX', 'ASP'])
    expect(matchSymbols(['A', 'B'], '')).toEqual(['A', 'B'])
  })
})
