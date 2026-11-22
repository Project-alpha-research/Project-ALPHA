// The stored tests as one table: idea, asset, date, trades, out-of-sample Sharpe, the reading
// words and the equity curve. The Overview shows the newest ten; Results › All tests shows them
// all with filters. A row opens the run report. Every number is the stored one.

import { useEffect, useState } from 'react'
import { getJSON } from '../api/client'
import type { components } from '../api/generated'
import { openRunDetail } from './actions'
import {
  filterChoices, filterRuns, formatDay, formatSharpe, ideaName, nextSort, NO_FILTER, plainError, readingCell, sortRuns, sparkPath,
  type RecentRun, type RunFilter, type Sort, type SortKey,
} from './recentTestsModel'
import './RecentTests.css'

type RecentRunList = components['schemas']['RecentRunList']
type Load = { state: 'loading' } | { state: 'ready'; value: RecentRunList } | { state: 'error'; text: string }

const COLUMNS: { key: SortKey | null; label: string; num?: boolean; title?: string }[] = [
  { key: 'idea', label: 'Idea' },
  { key: 'symbol', label: 'Asset' },
  { key: 'mtime', label: 'Tested' },
  { key: 'trades', label: 'Trades', num: true, title: 'Closed trades over the whole tested history' },
  { key: 'oos_sharpe', label: 'Out-of-sample Sharpe', num: true, title: 'Walk-forward out-of-sample Sharpe after costs, as stored' },
  { key: 'evidence', label: 'Reading' },
  { key: null, label: 'Equity' },
]

function Spark({ values }: { values: readonly number[] }) {
  const path = sparkPath(values, 96, 22, 2)
  if (!path) return <span className="muted">—</span>
  const rising = values[values.length - 1] >= values[0]
  return <svg className={`recent-spark ${rising ? 'up' : 'down'}`} width="96" height="22" viewBox="0 0 96 22" role="img" aria-label="Equity curve">
    <path d={path} fill="none" stroke="currentColor" strokeWidth="1.4" />
  </svg>
}

function Choice({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange(value: string): void }) {
  return <label>{label}<select className="field" value={value} onChange={event => onChange(event.target.value)}>
    <option value="">All</option>
    {options.map(option => <option key={option} value={option}>{option}</option>)}
  </select></label>
}

export function RecentTests({ limit = 10, filters = false }: { limit?: number; filters?: boolean }) {
  const [load, setLoad] = useState<Load>({ state: 'loading' })
  const [sort, setSort] = useState<Sort>({ key: 'mtime', descending: true })
  const [filter, setFilter] = useState<RunFilter>(NO_FILTER)
  useEffect(() => {
    let live = true
    getJSON<RecentRunList>(`/api/recent-runs?limit=${limit}`).then(
      value => { if (live) setLoad({ state: 'ready', value }) },
      (cause: unknown) => { if (live) setLoad({ state: 'error', text: plainError(cause, 'the stored tests') }) },
    )
    return () => { live = false }
  }, [limit])
  if (load.state === 'loading') return <div className="recent-tests" aria-busy="true"><div className="skeleton" style={{ height: 180 }} /></div>
  if (load.state === 'error') return <p className="recent-tests market-error" role="alert">{load.text}</p>
  const rows: RecentRun[] = load.value.items
  if (!rows.length) return <p className="recent-tests muted">No tests are stored yet. Ask Claude to test an idea; it appears here when it finishes.</p>
  const choices = filterChoices(rows)
  const shown = sortRuns(filterRuns(rows, filter), sort)
  const set = (patch: Partial<RunFilter>) => setFilter(previous => ({ ...previous, ...patch }))
  return <section className="recent-tests" aria-label={filters ? 'All tests' : 'Recent tests'}>
    {filters ? <div className="recent-filters" role="group" aria-label="Filter the tests">
      <Choice label="Asset" value={filter.asset} options={choices.assets} onChange={asset => set({ asset })} />
      <Choice label="Idea" value={filter.idea} options={choices.ideas} onChange={idea => set({ idea })} />
      <Choice label="Reading" value={filter.reading} options={choices.readings} onChange={reading => set({ reading })} />
      <span className="muted">{shown.length} of {load.value.total} tests</span>
    </div> : null}
    {!shown.length ? <p className="muted">No test matches these filters. Choose All in a filter to see more.</p> : <table className="blotter recent-table">
      <thead><tr>{COLUMNS.map(column => {
        const active = column.key === sort.key
        return <th key={column.label} className={column.num ? 'r' : undefined} title={column.title} aria-sort={active ? (sort.descending ? 'descending' : 'ascending') : undefined}>
          {column.key ? <button type="button" className="recent-sort" onClick={() => setSort(nextSort(sort, column.key as SortKey))}>
            {column.label}{active ? (sort.descending ? ' ▼' : ' ▲') : ''}</button> : column.label}
        </th>
      })}</tr></thead>
      <tbody>{shown.map(row => <tr key={row.run_id} className="recent-row" tabIndex={0} aria-label={`Open the report for ${ideaName(row)} on ${row.symbol ?? 'an unnamed asset'}`}
        onClick={() => openRunDetail(row.run_id)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); openRunDetail(row.run_id) } }}>
        <td className="recent-idea" title={ideaName(row)}>{ideaName(row)}</td>
        <td className="mono">{row.symbol ?? '—'}</td>
        <td className="recent-date">{formatDay(row.mtime)}</td>
        <td className="num mono">{row.trades ?? '—'}</td>
        <td className="num mono">{formatSharpe(row.oos_sharpe)}</td>
        <td>{(() => {
          const cell = readingCell(row)
          return cell.link
            ? <button type="button" className="link-button" onClick={event => { event.stopPropagation(); openRunDetail(row.run_id) }}>{cell.link}</button>
            : cell.words
        })()}</td>
        <td><Spark values={row.spark} /></td>
      </tr>)}</tbody>
    </table>}
  </section>
}

export function AllTests() {
  return <RecentTests limit={200} filters />
}
