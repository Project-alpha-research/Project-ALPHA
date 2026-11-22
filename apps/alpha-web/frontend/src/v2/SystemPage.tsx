// System: the last nightly run, how fresh the stored bars are, and the data home. Readings only.

import type { ReactNode } from 'react'
import { api } from '../api/client'
import { statusDot, type DeskStatus } from './deskModel'
import { Empty, Panel, Problem, Skeleton } from './parts'
import { useLoad, type Load } from './useLoad'

function gigabytes(bytes: number | null | undefined): string {
  return typeof bytes === 'number' ? `${(bytes / 1e9).toFixed(1)} GB` : '—'
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return <tr><th scope="row">{label}</th><td>{children}</td></tr>
}

function Nightly({ status }: { status: Load<DeskStatus> }) {
  if (status.state === 'loading') return <Skeleton rows={4} height={16} label="Loading the nightly record" />
  if (status.state === 'error') return <Problem>{status.text}</Problem>
  const night = status.value.nightly
  const dot = statusDot(status.value)
  if (!night) return <Empty>{status.value.nightly_problem ? `No nightly record could be read: ${status.value.nightly_problem}` : 'No nightly run is recorded yet. The nightly run writes one record each night.'}</Empty>
  return <>
    {dot ? <p className={`d-status-line ${dot.tone}`}><i aria-hidden="true" />{dot.text}</p> : null}
    <table className="d-table d-kv"><tbody>
      <Row label="Date">{night.date}{night.run_number ? ` · run ${night.run_number}` : ''}</Row>
      <Row label="Paths">{night.complete}</Row>
      <Row label="Problems">{night.blocking} blocking · {night.minor} minor</Row>
      <Row label="Ready to rely on">{night.ready ? 'Yes' : 'Not yet'}</Row>
    </tbody></table>
    {night.reasons.length ? <ul className="d-reasons">{night.reasons.map(reason => <li key={reason}>{reason}</li>)}</ul> : null}
  </>
}

export function SystemPage({ status }: { status: Load<DeskStatus> }) {
  const market = useLoad(() => api.marketOverview('1D', 90, 15), 'system-market', 'the stored-bar dates')
  const system = useLoad(() => api.system(), 'system', 'the data home facts')
  return <div className="d-grid-2">
    <Panel title="Nightly run"><Nightly status={status} /></Panel>
    <Panel title="Data">
      {market.state === 'loading' ? <Skeleton rows={3} height={16} label="Loading the stored-bar dates" />
        : market.state === 'error' ? <Problem>{market.text}</Problem>
        : <table className="d-table d-kv"><tbody>
          <Row label="Daily bars to">{market.value.data_to ? market.value.data_to.slice(0, 10) : 'No bars stored'}</Row>
          <Row label="Assets stored">{market.value.assets_in_store}</Row>
          <Row label="Held back from">{status.state === 'ready' ? `${status.value.reserved_start} (not used by tests)` : '—'}</Row>
          {market.value.too_few_bars.length ? <Row label="Too few bars">{market.value.too_few_bars.join(', ')}</Row> : null}
        </tbody></table>}
      {system.state === 'ready' ? <table className="d-table d-kv"><tbody>
        <Row label="Data home">{system.value.data_dir.readable ? 'Readable' : 'Not readable'}{system.value.data_dir.writable ? ', writable' : ''}</Row>
        <Row label="Free disk">{gigabytes(system.value.data_dir.free_bytes)}</Row>
        <Row label="Symbols · snapshots">{system.value.counts.symbols} · {system.value.counts.snapshots}</Row>
      </tbody></table> : system.state === 'error' ? <Problem>{system.text}</Problem> : null}
    </Panel>
  </div>
}
