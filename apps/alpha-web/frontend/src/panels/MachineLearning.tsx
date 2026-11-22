// Machine learning: stored runs made by `alpha ml run <spec>`. A display of what is stored; it
// starts no training. The server sends every number (`GET /api/ml-runs`, `GET /api/runs/{id}/equity`).

import { useEffect, useMemo, useState } from 'react'

import { getJSON } from '../api/client'
import type { EquitySeries, MlStoredRun, MlStoredRunList } from '../api/types'
import { CopyCommand } from '../components/CopyCommand'
import { MiniLine } from '../components/MiniLine'
import { CHART } from '../util/chartTheme'
import { EMPTY_STATE_TEXT, FIRST_RUN_COMMAND, READ_ONLY_NOTE, foldRows, readingWords, runTitle } from './mlRunsModel'
import { plainError } from './recentTestsModel'

type Load = { state: 'loading' } | { state: 'ready'; value: MlStoredRunList } | { state: 'error'; text: string }

function Charts({ runId }: { runId: string }) {
  const [curve, setCurve] = useState<EquitySeries | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    setCurve(null); setFailed(null)
    getJSON<EquitySeries>(`/api/runs/${runId}/equity`).then(
      value => { if (live) setCurve(value) },
      (cause: unknown) => { if (live) setFailed(plainError(cause, 'the equity curve')) },
    )
    return () => { live = false }
  }, [runId])
  const equity = useMemo(() => (curve ? curve.ts.map((t, i) => [t, curve.equity[i]] as [number, number]) : []), [curve])
  const drawdown = useMemo(() => (curve ? curve.ts.map((t, i) => [t, curve.drawdown[i] * 100] as [number, number]) : []), [curve])
  if (failed) return <p role="alert" className="market-error">{failed}</p>
  if (!curve) return <div className="skeleton" style={{ height: 220 }} aria-busy="true" />
  if (!equity.length) return <p className="muted">This run stored no equity curve.</p>
  const day = (value: number) => new Date(value * 1000).toISOString().slice(0, 10)
  return (
    <div className="ml-charts">
      <h4>Equity after costs</h4>
      <MiniLine chartId="ml.equity" series={[{ label: 'Equity', colour: CHART.accent, points: equity }]}
        xLabel="Day" yLabel="Account value" formatX={day} />
      <h4>Fall from the previous peak</h4>
      <MiniLine chartId="ml.drawdown" series={[{ label: 'Drawdown', colour: CHART.gold, points: drawdown }]}
        xLabel="Day" yLabel="Fall, %" formatX={day} />
    </div>
  )
}

export function MachineLearningView({ run }: { run: MlStoredRun }) {
  const rows = foldRows(run.folds)
  return (
    <article className="ml-run" aria-label={`Machine learning run ${run.run_id.slice(0, 8)}`}>
      <p>{run.split_sentence ?? 'This run did not store its folds.'}</p>
      <dl className="ml-facts">
        <dt>Assets</dt><dd>{run.assets.length ? run.assets.join(', ') : 'not recorded'}</dd>
        <dt>Model</dt><dd>{run.model}</dd>
        <dt>Costs</dt><dd>{run.costs}</dd>
      </dl>
      <h3>Reading</h3>
      {readingWords(run).map(line => <p key={line}>{line}</p>)}
      <Charts runId={run.run_id} />
      <h3>Folds</h3>
      {rows.length ? (
        <table className="blotter ml-folds">
          <thead><tr><th scope="col" className="r">Fold</th><th scope="col">Trained on</th><th scope="col">Tested on</th></tr></thead>
          <tbody>{rows.map(row => <tr key={row.fold}><td className="num mono">{row.fold}</td><td>{row.trained}</td><td>{row.tested}</td></tr>)}</tbody>
        </table>
      ) : <p className="muted">This run did not store its folds.</p>}
      {run.folds_total > rows.length ? <p className="muted">The table shows the first {rows.length} of {run.folds_total} folds.</p> : null}
    </article>
  )
}

export function MachineLearning() {
  const [load, setLoad] = useState<Load>({ state: 'loading' })
  const [selected, setSelected] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    getJSON<MlStoredRunList>('/api/ml-runs').then(
      value => { if (live) setLoad({ state: 'ready', value }) },
      (cause: unknown) => { if (live) setLoad({ state: 'error', text: plainError(cause, 'the stored machine learning runs') }) },
    )
    return () => { live = false }
  }, [])
  if (load.state === 'loading') return <div className="ml-window" aria-busy="true"><div className="skeleton" style={{ height: 180 }} /></div>
  if (load.state === 'error') return <p className="ml-window market-error" role="alert">{load.text}</p>
  const runs = load.value.items
  const run = runs.find(item => item.run_id === selected) ?? runs[0]
  return (
    <div className="ml-window" style={{ background: 'var(--panel)', color: 'var(--ink)', padding: 'var(--pad)' }}>
      <h2>Machine learning</h2>
      <p className="muted">{READ_ONLY_NOTE}</p>
      {!run ? (
        <>
          <p role="status">{EMPTY_STATE_TEXT}</p>
          <CopyCommand command={FIRST_RUN_COMMAND} why="Makes the first machine learning run. Your AI runs it; this window only reads the result." />
        </>
      ) : (
        <>
          <label>Run <select value={run.run_id} onChange={event => setSelected(event.target.value)}>
            {runs.map(item => <option key={item.run_id} value={item.run_id}>{item.run_id.slice(0, 8)} · {runTitle(item)}</option>)}
          </select></label>
          <MachineLearningView run={run} />
        </>
      )}
    </div>
  )
}
