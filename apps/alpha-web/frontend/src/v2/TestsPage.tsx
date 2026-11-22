// Tests: every stored run in one table, filtered by asset, idea and reading; a row opens its report.

import { useState } from 'react'
import { filterChoices, filterRuns, NO_FILTER, type RunFilter } from './deskModel'
import { readRecentRuns } from './deskApi'
import { Empty, Panel, Problem, Skeleton } from './parts'
import { useLoad } from './useLoad'
import { RunReport } from './RunReport'
import { RunsTable } from './RunsTable'

function Choice({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange(value: string): void }) {
  return <label className="d-field"><span>{label}</span>
    <select value={value} onChange={event => onChange(event.target.value)}>
      <option value="">All</option>
      {options.map(option => <option key={option} value={option}>{option}</option>)}
    </select>
  </label>
}

function RunsList({ onOpen }: { onOpen(runId: string): void }) {
  const load = useLoad(() => readRecentRuns(200), 'all-runs', 'the tests')
  const [filter, setFilter] = useState<RunFilter>(NO_FILTER)
  if (load.state === 'loading') return <Panel title="All tests"><Skeleton rows={10} height={22} label="Loading the tests" /></Panel>
  if (load.state === 'error') return <Panel title="All tests"><Problem>{load.text}</Problem></Panel>
  const rows = load.value.items
  const choices = filterChoices(rows)
  const shown = filterRuns(rows, filter)
  const set = (patch: Partial<RunFilter>) => setFilter(previous => ({ ...previous, ...patch }))
  return <Panel title="All tests" aside={<span className="d-muted">{shown.length} of {load.value.total} shown</span>}>
    <div className="d-filters" role="group" aria-label="Filter the tests">
      <Choice label="Asset" value={filter.asset} options={choices.assets} onChange={asset => set({ asset })} />
      <Choice label="Idea" value={filter.idea} options={choices.ideas} onChange={idea => set({ idea })} />
      <Choice label="Reading" value={filter.reading} options={choices.readings} onChange={reading => set({ reading })} />
      {filter !== NO_FILTER ? <button type="button" className="d-btn d-btn-quiet" onClick={() => setFilter(NO_FILTER)}>Clear filters</button> : null}
    </div>
    {!rows.length ? <Empty>No tests are stored yet. Ask Claude to test an idea; the run appears here when it finishes.</Empty>
      : !shown.length ? <Empty>No test matches these filters. Clear a filter to see more.</Empty>
      : <RunsTable rows={shown} onOpen={onOpen} caption="All stored tests" />}
  </Panel>
}

export function TestsPage({ runId, onOpen, onBack }: { runId: string | null; onOpen(runId: string): void; onBack(): void }) {
  if (!runId) return <RunsList onOpen={onOpen} />
  return <div className="d-stack">
    <nav className="d-crumbs" aria-label="Breadcrumb"><button type="button" className="d-link" onClick={onBack}>Tests</button><span aria-hidden="true">/</span><span className="mono">{runId}</span></nav>
    <RunReport key={runId} runId={runId} />
  </div>
}
