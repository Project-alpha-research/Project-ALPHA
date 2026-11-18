import { ChartSurface } from '../theme/ChartSurface'
import { Timestamp, formatDuration } from '../util/formatTime'
import { useEffect, useState, type CSSProperties } from 'react'
import { getJSON } from '../api/client'
import type { components } from '../api/generated'
import { Placeholder } from '../components/Placeholder'
import { Section } from './rundetail/common'
import { JourneyPicker } from './RdAgentJourney'

type Schema = components['schemas']
export type Fact = Schema['RecordedFact']
export type Run = Schema['RdAgentRun']
export type Detail = Schema['RdAgentDetail']
type RunList = Schema['RdAgentRunList']

const NOTICE = 'Exploratory results. Nothing here is evidence of an edge until a candidate is confirmed on reserved data.'
const FUNNEL: Record<string, string> = {
  proposed: 'ideas proposed', refused_closed_family: 'refused: idea family already closed',
  stopped_by_provider: 'stopped by the model provider',
  code_ran: 'code ran', passed_rank_screen: 'passed the ranking test',
  passed_spread_check: 'top third beat the bottom third',
  shortlisted: 'shortlisted (passed all but the many-tries correction)',
  passed_deflation: 'survived the multiple-testing check',
}
const LABELS: Record<string, string> = {
  q: 'Ranking test, adjusted probability', p: 'Ranking test, probability', mean_ic: 'Average rank correlation',
  dsr: 'Deflated Sharpe probability', psr: 'Probability of a positive Sharpe', n_trials: 'Trials used',
  passed: 'Recorded pass', counted_only: 'Counted toward testing only; not a result',
  shortlist: 'Shortlisted (bookkeeping only, not a pass)', lineage_r2: 'Blend of earlier tries: adjusted R²',
  lineage_regressors: 'Earlier factors used', lineage_convention: 'Lineage convention',
  lineage_reason: 'Lineage calculation note', composite_suspect: 'Looks like a blend of earlier tries',
  net_annual_excess: 'Annual excess return after costs', gross_annual_excess: 'Annual excess return before costs',
  haircuts_applied: 'Write-offs applied', writeoff_instruments: 'Coins written off',
  universe_includes_delisted: 'Includes later-delisted instruments', universe_text: 'Recorded universe description',
  local_embedding_calls: 'Local embedding calls', provider_embedding_calls: 'Paid embedding calls',
  cache_hit_rate: 'Cache hit rate (fraction)', 'mean_ci_95.lower': '95% range, low end', 'mean_ci_95.upper': '95% range, high end', instruments_ended_early: 'Instruments whose data ended early',
}
const surface: CSSProperties = {
  background: 'var(--panel)', color: 'var(--ink)', padding: 'var(--pad)', minHeight: '100%',
} as CSSProperties

function factText(fact: Fact | undefined): string {
  if (fact?.value === null || fact?.value === undefined) return fact?.reason ?? 'not recorded by this run'
  if (typeof fact.value === 'boolean') return fact.value ? 'Yes' : 'No'
  if (typeof fact.value === 'number') return String(Number(fact.value.toPrecision(5)))
  return Array.isArray(fact.value) ? fact.value.join(', ') || 'None recorded' : String(fact.value)
}

function RecordedFact({ name, fact }: { name: string; fact: Fact | undefined }) {
  if ((name.endsWith('_at') || name === 'as_of') && typeof fact?.value === 'string') {
    return <Timestamp value={fact.value} />
  }
  if (name === 'minutes' && typeof fact?.value === 'number') return <span>{formatDuration(fact.value)}</span>
  return <>{factText(fact)}</>
}

function Facts({ facts }: { facts: Record<string, Fact> }) {
  return <dl style={{ display: 'grid', gridTemplateColumns: 'minmax(140px, 1fr) 2fr', gap: 6 }}>
    {Object.entries(facts).map(([name, value]) => <div key={name} style={{ display: 'contents' }}>
      <dt>{LABELS[name] ?? name.replaceAll('_', ' ').replaceAll('.', ' / ')}</dt>
      <dd style={{ margin: 0, overflowWrap: 'anywhere' }}><RecordedFact name={name} fact={value} /></dd>
    </div>)}
  </dl>
}

function Meter({ label, cap }: { label: string; cap: Schema['RdAgentCap'] | undefined }) {
  const used = cap?.used.value
  const limit = cap?.limit.value
  const known = typeof used === 'number' && typeof limit === 'number' && limit > 0 && used >= 0
  return <div style={{ marginBottom: 12 }}>
    <div>{label}: {factText(cap?.used)} / {factText(cap?.limit)}</div>
    {known && <div role="meter" aria-label={label} aria-valuenow={used} aria-valuemin={0} aria-valuemax={Math.max(used, limit)} aria-valuetext={`${used} of ${limit}`} style={{ border: '1px solid var(--line-strong)', height: 10 }}>
      <div style={{ width: `${Math.min(100, used / limit * 100)}%`, height: '100%', background: 'var(--accent)' }} />
    </div>}
  </div>
}

function RunDetail({ detail }: { detail: Detail }) {
  const maximum = Math.max(1, ...Object.values(detail.funnel).map(fact => typeof fact.value === 'number' ? fact.value : 0))
  return <>
    <Section title="Ideas through the checks">
      <p>Shortlisted means the declared primary screen, spread check and replay passed. Shortlisted is not a pass, not a candidate, and not evidence of profit.</p>
      <ChartSurface id="rd-agent.funnel">
      {Object.entries(FUNNEL).map(([key, label]) => {
        const value = detail.funnel[key]
        return <div key={key} style={{ marginBottom: 8 }}>
          <div>{label}: {factText(value)}{value?.basis && <span className="muted"> ({value.basis})</span>}</div>
          {typeof value?.value === 'number' && <div aria-hidden="true" style={{ width: `${value.value / maximum * 100}%`, minWidth: value.value ? 2 : 0, height: 8, background: 'var(--chart-accent)' }} />}
        </div>
      })}
      </ChartSurface>
    </Section>
    <Section title="Recorded caps">
      <Meter label="Calls" cap={detail.caps.calls} />
      <Meter label="USD this run" cap={detail.caps.run_usd} />
      <Meter label="USD this month" cap={detail.caps.month_usd} />
      <p className="muted">Monthly spend is the snapshot at the end of this run, not today's balance.</p>
    </Section>
    <Section title="Factors">
      {detail.factor_reason && <p>{detail.factor_reason}</p>}
      {!detail.factors.length && <p>No factor trials were recorded for this run.</p>}
      {detail.factors.map((factor, index) => <details key={`${index}-${factText(factor.name)}`} style={{ padding: '8px 0', borderBottom: '1px solid var(--line-strong)' }}>
        <summary><strong>{factText(factor.name)}</strong> <span className="chip">{factor.status}</span> {factor.sentence}</summary>
        <p>{factText(factor.description)}</p>
        <Facts facts={{ idea_families: factor.idea_families, failure_reason: factor.failure_reason, ...factor.figures }} />
        {Object.entries(factor.clocks).map(([clock, data]) => <section key={clock}>
          <h3>{clock}</h3><Facts facts={data.figures} />
          {data.replay.counted_only?.value != null && <p><strong>Trial accounting only: {factText(data.replay.counted_only)}</strong></p>}
          {Object.entries({ 'Ranking test': data.screen, 'Spread check': data.spread, 'Replay and write-offs': data.replay, 'Multiple-testing check': data.deflation, 'Family deflation': data.family_deflation }).map(([label, facts]) => <details key={label}><summary>{label}</summary><Facts facts={facts} /></details>)}
        </section>)}
      </details>)}
      <details style={{ marginBottom: 16 }}><summary>Proposals stopped before evaluation</summary>
        {detail.refusal_reason && <p>{detail.refusal_reason}</p>}
        {detail.refusals.map((row, i) => <Facts key={i} facts={row} />)}
      </details>
    </Section>
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 16 }}>
      <Section title="Universe">
        <Facts facts={Object.fromEntries(Object.entries(detail.universe).filter(([key]) => key !== 'instruments'))} />
        <details><summary>Instruments in the universe</summary><p>{factText(detail.universe.instruments)}</p></details>
        <details><summary>Tickers split or rescaled</summary>
          {detail.identity_splits.map((row, i) => <Facts key={`split-${i}`} facts={row} />)}
          {detail.identity_rescales.map((row, i) => <Facts key={`rescale-${i}`} facts={row} />)}
          {!detail.identity_splits.length && !detail.identity_rescales.length && <p>No identity correction entries recorded.</p>}
        </details>
      </Section>
      <Section title="Cost and cache">
        <Facts facts={{ cost_usd: detail.run.cost_usd, counted_calls: detail.run.counted_calls, local_embedding_calls: detail.run.local_embedding_calls, provider_embedding_calls: detail.run.provider_embedding_calls, ...detail.cache }} />
        <details><summary>Recorded providers and monthly snapshots</summary><Facts facts={detail.providers} />
          {Object.entries(detail.months).map(([month, facts]) => <section key={month}><h3>{month}</h3><Facts facts={facts} /></section>)}
        </details>
      </Section>
    </div>
    <Section title="Step timing"><p>Start and end times as recorded; minutes are the end time minus the start time.</p>
      {detail.timing_reason && <p>{detail.timing_reason}</p>}
      {detail.timing.length > 0 && <table style={{ borderCollapse: 'collapse' }}>
        <thead><tr><th>Round</th><th>Step</th><th>Started</th><th>Ended</th><th>Duration</th><th>Result</th></tr></thead>
        <tbody>{detail.timing.map((row, i) => <tr key={i}>
          {['loop', 'step', 'started_at', 'ended_at', 'minutes', 'status'].map(key => <td key={key} style={{ padding: '2px 8px', overflowWrap: 'anywhere' }}><RecordedFact name={key} fact={row[key]} /></td>)}
        </tr>)}</tbody>
      </table>}
    </Section>
    <Section title="ALPHA's recorded notes">{detail.notes.length ? detail.notes.map((note, i) => <p key={i}>{note}</p>) : <p>No notes were recorded.</p>}</Section>
  </>
}

function SelectedRun({ detail }: { detail: Detail }) {
  const { outcome, started_at, ended_at, rounds_completed } = detail.run
  const fields = Object.entries({ outcome, started_at, ended_at, rounds_completed })
    .filter(([, fact]) => fact?.value != null)
  const counts = Object.entries(detail.story?.journey ?? {}).filter(([, fact]) => fact?.value != null)
  return <>
    <h2>{detail.run.folder}</h2>
    {fields.length > 0 && <Facts facts={Object.fromEntries(fields)} />}
    {counts.length > 0 && <p>{counts.map(([stage, value]) => <span key={stage} style={{ marginRight: 'var(--pad)' }}>
      {stage === 'shortlisted' ? 'shortlisted (not a pass)' : stage}: {factText(value)}
    </span>)}</p>}
    {!fields.length && !counts.length && <p className="muted">This run stored no summary.</p>}
    <JourneyPicker runId={detail.run.run_id} ideas={detail.journeys ?? []} />
    <details><summary>Technical detail for this run</summary><RunDetail detail={detail} /></details>
  </>
}

export function RdAgentView({ list, selected, detail, error, onSelect }: {
  list: RunList | null; selected: string | null; detail: Detail | null; error: string | null; onSelect: (id: string) => void
}) {
  return <div className="panel"><div className="panel-body" tabIndex={0}><div style={surface}>
    <p style={{ background: 'var(--panel)', padding: 'var(--pad-sm)', borderBottom: 'thin solid var(--line-strong)' }}>{NOTICE}</p>
    {error && <p role="alert">{error}</p>}
    {!list && !error && <Placeholder>Loading recorded runs…</Placeholder>}
    {list && !list.items.length && <Placeholder big="No RD-Agent runs">{list.reason ?? 'No recorded factor runs were found.'}</Placeholder>}
    {list && !list.items.length && list.ledger_reason && <details>
      <summary>Technical detail</summary><p>{list.ledger_reason}</p>
    </details>}
    {list && list.items.length > 0 && <div className="rdagent-run-layout">
      <nav aria-label="RD-Agent runs" style={{ maxHeight: '75vh', overflowY: 'auto', alignSelf: 'start' }}>{list.items.map(run => <button key={run.run_id} type="button" aria-pressed={selected === run.run_id} onClick={() => onSelect(run.run_id)} style={{ display: 'block', width: '100%', textAlign: 'left', padding: 'var(--pad-sm)', marginBottom: 'var(--pad-sm)', overflowWrap: 'anywhere', background: 'var(--panel)', color: 'var(--ink)', border: `thin solid var(${selected === run.run_id ? '--accent' : '--line-strong'})` }}>
        <strong>{run.folder}</strong>
        {run.started_at?.value != null && <><br /><RecordedFact name="started_at" fact={run.started_at} /></>}
        {run.outcome?.value != null && <><br />{factText(run.outcome)}</>}
      </button>)}</nav>
      <main aria-label="Selected RD-Agent run" aria-live="polite">{detail?.run.run_id === selected ? <SelectedRun key={selected} detail={detail} /> : !error && <Placeholder>{selected ? 'Loading recorded run…' : 'Select a run to see what happened.'}</Placeholder>}</main>
    </div>}
  </div></div></div>
}

function loadRdAgentRun(id: string): Promise<Detail> {
  return getJSON<Detail>(`/api/rdagent/runs/${encodeURIComponent(id)}`)
}

export function RdAgentPanel() {
  const [list, setList] = useState<RunList | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [detail, setDetail] = useState<Detail | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    getJSON<RunList>('/api/rdagent/runs').then(value => {
      if (live) { setList(value); setSelected(value.items[0]?.run_id ?? null) }
    }).catch(() => { if (live) setError('The recorded RD-Agent runs could not be read. Refresh to try again.') })
    return () => { live = false }
  }, [])
  useEffect(() => {
    let live = true
    if (selected) loadRdAgentRun(selected).then(value => {
      if (live) { setDetail(value); setError(null) }
    }).catch(() => { if (live) setError('This recorded run could not be read. Select another run or refresh to try again.') })
    return () => { live = false }
  }, [selected])
  return <RdAgentView list={list} selected={selected} detail={detail} error={error} onSelect={id => { setError(null); setSelected(id) }} />
}
