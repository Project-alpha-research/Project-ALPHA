// Pure decisions behind the Workstation desk: places and their URLs, plain error words, the
// recent-tests table (sort, filter, sparkline path) and the frame's status dot. Every number shown
// is the server's; these functions only order, filter and format it.

import type { components } from '../api/generated'

export type DeskRun = components['schemas']['DeskRun']
export type DeskStatus = components['schemas']['DeskStatus']

export const PLACES = [
  { id: 'home', label: 'Home', title: 'Today' },
  { id: 'charts', label: 'Charts', title: 'Charts' },
  { id: 'ideas', label: 'Ideas', title: 'Ideas' },
  { id: 'tests', label: 'Tests', title: 'Tests' },
  { id: 'setup', label: 'Setup Lab', title: 'Setup Lab' },
  { id: 'rdagent', label: 'RD-Agent', title: 'RD-Agent' },
  { id: 'system', label: 'System', title: 'System' },
] as const
export type Place = (typeof PLACES)[number]['id']

export interface Route { place: Place; run: string | null; symbol: string | null }

/**
 * The old shell keeps `#legacy` and its own links (`#page=…`, `#run=…` without a desk place) until
 * later slices replace it.
 */
export function isLegacyHash(hash: string): boolean {
  if (/^#legacy\b/.test(hash)) return true
  const params = new URLSearchParams(hash.replace(/^#/, ''))
  return !params.has('place') && (params.has('page') || params.has('pane') || params.has('run'))
}

export function parseRoute(hash: string): Route {
  const params = new URLSearchParams(hash.replace(/^#/, ''))
  const wanted = params.get('place')
  const place = PLACES.find(item => item.id === wanted)?.id ?? 'home'
  const run = params.get('run')
  return { place, run: run && /^[0-9a-f]{16}$/.test(run) ? run : null, symbol: params.get('symbol') || null }
}

export function routeHash(route: { place: Place; run?: string | null; symbol?: string | null }): string {
  const params = new URLSearchParams({ place: route.place })
  if (route.run) params.set('run', route.run)
  if (route.symbol) params.set('symbol', route.symbol)
  return `#${params.toString()}`
}

export function placeTitle(place: Place): string {
  return PLACES.find(item => item.id === place)?.title ?? 'Today'
}

/**
 * What failed and what to try, in one plain sentence pair. The status code, request id and stack
 * are dropped; the server's own message stays.
 */
export function plainError(cause: unknown, what: string): string {
  const raw = cause instanceof Error ? cause.message : String(cause)
  const message = raw.replace(/\s*\[request [^\]]*\]\s*$/, '').replace(/^\d{3}(\s[A-Za-z ]+)?\s*—\s*/, '').trim()
  const generic = !message || message === 'The Workstation request failed.' || /Failed to fetch|NetworkError/i.test(message)
  const detail = generic ? 'The server did not answer.' : message.replace(/\.?$/, '.')
  return `Could not load ${what}. ${detail} Check that the Workstation server is running, then reload the page.`
}

export function formatNumber(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—'
  return value.toFixed(digits)
}

export function signTone(value: number | null | undefined): 'up' | 'down' | '' {
  if (value === null || value === undefined || !Number.isFinite(value) || value === 0) return ''
  return value > 0 ? 'up' : 'down'
}

/** A file time (epoch seconds) as `22 Nov 2026`, in UTC. */
export function formatDay(seconds: number): string {
  return new Date(seconds * 1000).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })
}

/** `2023-12-29T00:00:00+00:00` as `2023-12-29`; a missing date stays `—`. */
export function isoDay(value: string | null | undefined): string {
  return value ? value.slice(0, 10) : '—'
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

export function sparkTone(values: readonly number[]): 'up' | 'down' | '' {
  const finite = values.filter(Number.isFinite)
  return finite.length < 2 ? '' : signTone(finite[finite.length - 1] - finite[0])
}

export type SortKey = 'idea' | 'symbol' | 'mtime' | 'trades' | 'oos_sharpe' | 'evidence'
export interface Sort { key: SortKey; descending: boolean }
export interface RunFilter { asset: string; idea: string; reading: string }
export const NO_FILTER: RunFilter = { asset: '', idea: '', reading: '' }

export function ideaName(run: DeskRun): string {
  return run.idea || run.rule_name || run.display_name
}

function sortValue(run: DeskRun, key: SortKey): string | number | null {
  if (key === 'idea') return ideaName(run).toLowerCase()
  if (key === 'symbol') return (run.symbol ?? '').toLowerCase()
  if (key === 'evidence') return run.evidence ?? null
  return run[key]
}

/** Stable sort; a missing value always sorts last, whichever way the column runs. */
export function sortRuns(rows: readonly DeskRun[], sort: Sort): DeskRun[] {
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

export function filterRuns(rows: readonly DeskRun[], filter: RunFilter): DeskRun[] {
  return rows.filter(row => (!filter.asset || row.symbol === filter.asset)
    && (!filter.idea || ideaName(row) === filter.idea)
    && (!filter.reading || (row.evidence ?? '') === filter.reading))
}

export function filterChoices(rows: readonly DeskRun[]): { assets: string[]; ideas: string[]; readings: string[] } {
  const unique = (values: (string | null)[]) => Array.from(new Set(values.filter((v): v is string => Boolean(v)))).sort()
  return { assets: unique(rows.map(r => r.symbol)), ideas: unique(rows.map(ideaName)), readings: unique(rows.map(r => r.evidence)) }
}

export interface Dot { tone: 'ok' | 'warn' | 'bad'; text: string }

/** The frame's status dot: the last nightly run as recorded; nothing when no answer came. */
export function statusDot(status: DeskStatus | null): Dot | null {
  if (!status) return null
  const night = status.nightly
  if (!night) return status.nightly_problem ? { tone: 'warn', text: `No nightly record could be read: ${status.nightly_problem}` } : null
  const label = `Last nightly run ${night.date}${night.run_number ? ` (#${night.run_number})` : ''}: ${night.complete}.`
  if (night.blocking > 0) return { tone: 'bad', text: `${label} ${night.blocking} blocking problem${night.blocking === 1 ? '' : 's'}. Open System for details.` }
  if (night.minor > 0) return { tone: 'warn', text: `${label} ${night.minor} minor problem${night.minor === 1 ? '' : 's'}.` }
  return { tone: 'ok', text: `${label} No problems.` }
}

/** Arrow keys step through the gallery and wrap at the ends. */
export function stepIndex(index: number, delta: number, count: number): number {
  return count ? (index + delta + count) % count : 0
}

/** Case-insensitive prefix match first, then contains; at most `limit` symbols. */
export function matchSymbols(symbols: readonly string[], text: string, limit = 8): string[] {
  const query = text.trim().toUpperCase()
  if (!query) return symbols.slice(0, limit)
  const starts = symbols.filter(s => s.toUpperCase().startsWith(query))
  const contains = symbols.filter(s => !s.toUpperCase().startsWith(query) && s.toUpperCase().includes(query))
  return [...starts, ...contains].slice(0, limit)
}
