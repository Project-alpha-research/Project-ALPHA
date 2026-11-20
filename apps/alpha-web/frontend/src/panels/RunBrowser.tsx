// Run Browser — the stored-run blotter, live: refetches whenever the activity stream reports a
// store change (whoever caused it — UI, CLI, Claude via MCP). Search + kind filter + sortable
// columns; click selects + broadcasts, Enter/double-click/⏎ button opens the run story.

import { useEffect, useMemo, useState } from 'react'

import { api } from '../api/client'
import type { RunListItem } from '../api/types'
import { DataTable } from '../components/DataTable'
import { Placeholder } from '../components/Placeholder'
import { setLinked } from '../context/linked'
import { useActivityField } from '../state/activity'
import { openRunDetail } from './actions'
import { runKindMatches } from './runBrowserModel'
import { runBrowserColumns } from './runBrowserColumns'
import type { PanelHandleProps } from '../context/panelHandle'

const KINDS = ['all', 'runs', 'optim', 'portfolio', 'cross_sectional', 'propfirm', 'forecast']

export function RunBrowser(props: PanelHandleProps) {
  const params = props.params as {
    defaultKind?: string
    defaultCommand?: string
    allowedKinds?: string[]
  } | undefined
  const allowedKinds = useMemo(
    () => Array.isArray(params?.allowedKinds)
      ? params.allowedKinds.filter((kind) => kind !== 'all' && KINDS.includes(kind))
      : [],
    [params?.allowedKinds],
  )
  const kindOptions = allowedKinds.length > 0 ? ['all', ...allowedKinds] : KINDS
  const requestedKind = String(
    params?.defaultKind ?? 'all',
  )
  const defaultKind = kindOptions.includes(requestedKind) ? requestedKind : 'all'
  const defaultCommand = String(
    params?.defaultCommand ?? '',
  )
  const [items, setItems] = useState<RunListItem[] | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [kind, setKind] = useState(defaultKind)
  const runsVersion = useActivityField('runsVersion')

  useEffect(() => {
    let live = true
    // small debounce: bursts of store events collapse into one refetch
    const t = window.setTimeout(() => {
      api
        .runs('?limit=500')
        .then((r) => {
          if (!live) return
          setItems(r.items)
          setError(null)
        })
        .catch((e: unknown) => live && setError(String(e)))
    }, 150)
    return () => {
      live = false
      window.clearTimeout(t)
    }
  }, [runsVersion])

  const filtered = useMemo(
    () => (items ?? []).filter(
      (r) => runKindMatches(r.kind, kind, allowedKinds)
        && (!defaultCommand || r.command === defaultCommand),
    ),
    [allowedKinds, defaultCommand, items, kind],
  )

  const columns = useMemo(() => runBrowserColumns(), [])

  function selectRow(run: RunListItem): void {
    setSelected(run.run_id)
    setLinked({
      runId: run.run_id,
      ...(run.symbol ? { symbol: run.symbol } : {}),
      snapshotId: run.snapshot_id,
    })
  }

  return (
    <div className="panel">
      <div className="panel-toolbar">
        <span className="title">Runs</span>
        {items ? <span className="count">{filtered.length}</span> : null}
        <input
          className="field toolbar-search"
          aria-label="Search runs"
          placeholder="search…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select
          className="field"
          aria-label="Filter runs by kind"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
        >
          {kindOptions.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </select>
      </div>
      <div className="panel-body">
        {error ? (
          <Placeholder big="error">{error}</Placeholder>
        ) : items === null ? (
          <Placeholder>loading…</Placeholder>
        ) : (
          <DataTable
            data={filtered}
            columns={columns}
            globalFilter={query}
            initialSorting={[{ id: 'mtime', desc: true }]}
            onRowClick={selectRow}
            onRowDoubleClick={(r) => openRunDetail(r.run_id)}
            onRowEnter={(r) => openRunDetail(r.run_id)}
            rowClass={(r) => (selected === r.run_id ? 'sel' : '')}
            empty={
              <Placeholder big="no runs yet">
                Launch one from the Strategy Lab or CLI, e.g. <code>alpha backtest run SPY</code>
              </Placeholder>
            }
          />
        )}
      </div>
    </div>
  )
}
