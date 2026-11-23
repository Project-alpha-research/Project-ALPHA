// Pure decisions behind the recent-tests table (Overview and Results › All tests): sort, filter,
// plain error words and the sparkline path. Every number is the server's; nothing is computed here.

import type { components } from '../api/generated'

export type RecentRun = components['schemas']['RecentRun']

export type SortKey = 'idea' | 'symbol' | 'mtime' | 'trades' | 'oos_sharpe' | 'evidence'
export interface Sort { key: SortKey; descending: boolean }
export interface RunFilter { asset: string; idea: string; reading: string }
export const NO_FILTER: RunFilter = { asset: '', idea: '', reading: '' }

export function ideaName(run: RecentRun): string {
  return run.idea || run.rule_name || run.display_name
}

export const OLDER_RUN_LINK = 'older run: open the report'

/** The Reading cell: the stored or worked-out words, or a link to the report when there are none. */
export function readingCell(run: RecentRun): { words: string | null; link: string | null } {
  return run.evidence ? { words: run.evidence, link: null } : { words: null, link: OLDER_RUN_LINK }
}

function sortValue(run: RecentRun, key: SortKey): string | number | null {
  if (key === 'idea') return ideaName(run).toLowerCase()
  if (key === 'symbol') return (run.symbol ?? '').toLowerCase()
  if (key === 'evidence') return run.evidence ?? null
  return run[key]
}

/** Stable sort; a missing value always sorts last, whichever way the column runs. */
export function sortRuns(rows: readonly RecentRun[], sort: Sort): RecentRun[] {
  return rows.map((row, index) => ({ row, index })).sort((a, b) => {
    const left = sortValue(a.row, sort.key), right = sortValue(b.row, sort.key)
    if (left === null && right === null) return a.index - b.index
    if (left === null) return 1
    if (right === null) return -1
    const order = left < right ? -1 : left > right ? 1 : 0
    return (sort.descending ? -order : order) || a.index - b.index
  }).map(item => item.row)
}

export function nextSort(current: Sort, key: SortKey): Sort {
  if (current.key === key) return { key, descending: !current.descending }
  return { key, descending: key === 'mtime' || key === 'oos_sharpe' || key === 'trades' }
}

export function filterRuns(rows: readonly RecentRun[], filter: RunFilter): RecentRun[] {
  return rows.filter(row => (!filter.asset || row.symbol === filter.asset)
    && (!filter.idea || ideaName(row) === filter.idea)
    && (!filter.reading || (row.evidence ?? '') === filter.reading))
}

export function filterChoices(rows: readonly RecentRun[]): { assets: string[]; ideas: string[]; readings: string[] } {
  const unique = (values: (string | null)[]) => Array.from(new Set(values.filter((v): v is string => Boolean(v)))).sort()
  return { assets: unique(rows.map(r => r.symbol)), ideas: unique(rows.map(ideaName)), readings: unique(rows.map(r => r.evidence)) }
}

export function formatSharpe(value: number | null): string {
  return value === null || !Number.isFinite(value) ? '—' : value.toFixed(2)
}

/** A file time (epoch seconds) as `22 Nov 2026`, in UTC. */
export function formatDay(seconds: number): string {
  return new Date(seconds * 1000).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
}

/** An SVG path through the values, scaled to the box; fewer than two finite values draw nothing. */
export function sparkPath(values: readonly number[], width: number, height: number, pad = 1): string {
  const finite = values.filter(Number.isFinite)
  if (finite.length < 2) return ''
  const low = Math.min(...finite), high = Math.max(...finite)
  const span = high - low || 1
  const step = (width - pad * 2) / (finite.length - 1)
  return finite.map((value, index) => {
    const x = pad + index * step
    const y = pad + (height - pad * 2) * (1 - (value - low) / span)
    return `${index ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`
  }).join(' ')
}

/**
 * What failed and what to try, in plain words. The status code and request id are dropped; the
 * server's own message stays.
 */
export function plainError(cause: unknown, what: string): string {
  const raw = cause instanceof Error ? cause.message : String(cause)
  const message = raw.replace(/\s*\[request [^\]]*\]\s*$/, '').replace(/^\d{3}(\s[A-Za-z ]+)?\s*—\s*/, '').trim()
  const generic = !message || /Failed to fetch|NetworkError/i.test(message)
  const detail = generic ? 'The server did not answer.' : message.replace(/\.?$/, '.')
  return `Could not load ${what}. ${detail} Check that the Workstation server is running, then reload the page.`
}
