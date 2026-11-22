// The tests table: one row per stored run, sortable by every column; a row opens the run report.

import { useState } from 'react'
import {
  formatDay, formatNumber, ideaName, nextSort, signTone, sortRuns, type DeskRun, type Sort, type SortKey,
} from './deskModel'
import { Sparkline } from './parts'

const COLUMNS: { key: SortKey | null; label: string; align?: 'r'; title?: string }[] = [
  { key: 'idea', label: 'Idea' },
  { key: 'symbol', label: 'Asset' },
  { key: 'mtime', label: 'Tested' },
  { key: 'trades', label: 'Trades', align: 'r', title: 'Closed trades over the whole tested history' },
  { key: 'oos_sharpe', label: 'OOS Sharpe', align: 'r', title: 'Walk-forward out-of-sample Sharpe after costs, as stored' },
  { key: 'evidence', label: 'Reading' },
  { key: null, label: 'Equity' },
]

export function RunsTable({ rows, onOpen, sortable = true, caption }: { rows: readonly DeskRun[]; onOpen(runId: string): void; sortable?: boolean; caption: string }) {
  const [sort, setSort] = useState<Sort>({ key: 'mtime', descending: true })
  const shown = sortable ? sortRuns(rows, sort) : rows
  return <table className="d-table d-runs">
    <caption className="sr-only">{caption}</caption>
    <thead><tr>{COLUMNS.map(column => {
      const active = sortable && column.key === sort.key
      return <th key={column.label} scope="col" className={column.align} title={column.title}
        aria-sort={active ? (sort.descending ? 'descending' : 'ascending') : undefined}>
        {sortable && column.key ? <button type="button" className="d-sort" onClick={() => setSort(nextSort(sort, column.key as SortKey))}>
          {column.label}<span className="d-sort-mark" aria-hidden="true">{active ? (sort.descending ? '▼' : '▲') : ''}</span>
        </button> : column.label}
      </th>
    })}</tr></thead>
    <tbody>{shown.map(row => <tr key={row.run_id} className="d-row-link" tabIndex={0} aria-label={`Open the report for ${ideaName(row)} on ${row.symbol ?? 'an unnamed asset'}`}
      onClick={() => onOpen(row.run_id)} onKeyDown={event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); onOpen(row.run_id) } }}>
      <td className="d-idea"><span className="d-idea-name">{ideaName(row)}</span>{row.rule_name && row.idea ? <span className="d-idea-sub mono">{row.rule_name}</span> : null}</td>
      <td className="mono d-asset">{row.symbol ?? '—'}</td>
      <td className="d-nowrap">{formatDay(row.mtime)}</td>
      <td className="r mono">{row.trades ?? '—'}</td>
      <td className={`r mono ${signTone(row.oos_sharpe)}`}>{formatNumber(row.oos_sharpe)}</td>
      <td>{row.evidence ? <span className="d-chip">{row.evidence}</span> : <span className="d-muted">not stored</span>}</td>
      <td className="d-spark-cell"><Sparkline values={row.spark} /></td>
    </tr>)}</tbody>
  </table>
}
