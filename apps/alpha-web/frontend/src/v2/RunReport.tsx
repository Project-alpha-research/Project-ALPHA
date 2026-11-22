// The run report: what was tested in one sentence, the reading in plain words, the interactive
// charts, the stored figure pairs and the trades. Every number is the stored one.

import { api } from '../api/client'
import type { RunDetail, TradeRow } from '../api/types'
import { ReadingBlock } from '../components/ReadingBlock'
import { TearSheetStack } from '../components/tearsheet/TearSheetStack'
import { parseReading } from '../panels/readingModel'
import { summaryNumbers, type RuleManifest } from '../panels/ruleTestModel'
import { workflowHash } from '../shell/workflowModel'
import { DeskChartSurface } from './DeskChartSurface'
import { formatNumber, isoDay, signTone } from './deskModel'
import { FigureGallery } from './FigureGallery'
import { Empty, Panel, Problem, Skeleton } from './parts'
import { useLoad } from './useLoad'

const FLAG_WORDS: Record<string, string> = {
  'below-benchmark': 'Holding the market had a higher risk-adjusted score.',
  'drawdown-with-market': 'The market also fell during the rule’s worst drop.',
  'concentrated-profit': 'A few trades made most of the profit.',
  'fragile-to-costs': 'The result changed a lot with trading costs.',
  'fragile-to-parameters': 'Changing the rule settings changed the result.',
  'fragile-to-delay': 'Trading one bar later changed the result.',
  'fragile-to-price-noise': 'Small price changes changed the result.',
  'implausibly-good': 'The result looks unusually strong.',
}

type Counts = { family_trials?: number; trial_n?: number }
type StoredReading = { counts?: Counts; count_sentence?: string; sentence?: string; evidence?: { word?: string; because?: string[] } }
type Spine = { costs?: { line?: string }; periods?: Record<string, { strategy?: { sharpe?: number | null }; benchmark?: { sharpe?: number | null } }> }

function Fact({ label, value, title }: { label: string; value: string; title?: string }) {
  return <div className="d-fact" title={title}><span>{label}</span><strong className="mono">{value}</strong></div>
}

function TradesTable({ runId }: { runId: string }) {
  const load = useLoad<TradeRow[]>(() => api.trades(runId), `trades:${runId}`, 'the trades')
  if (load.state === 'loading') return <Skeleton rows={5} height={18} label="Loading the trades" />
  if (load.state === 'error') return <Problem>{load.text}</Problem>
  if (!load.value.length) return <Empty>This test closed no trades, so there is nothing to list.</Empty>
  const money = (value: unknown, digits = 2) => typeof value === 'number' ? value.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits }) : '—'
  return <div className="d-scroll-x"><table className="d-table d-trades">
    <caption className="sr-only">Closed trades of this test</caption>
    <thead><tr><th scope="col">#</th><th scope="col">Entry</th><th scope="col">Exit</th><th scope="col">Side</th><th scope="col" className="r">Quantity</th>
      <th scope="col" className="r">Entry price</th><th scope="col" className="r">Exit price</th><th scope="col" className="r">Profit</th><th scope="col" className="r">Return</th></tr></thead>
    <tbody>{load.value.map((row, index) => {
      const ret = typeof row.realized_return === 'number' ? row.realized_return : null
      return <tr key={index}><td className="mono d-muted">{index + 1}</td><td className="mono">{isoDay(String(row.entry_ts ?? ''))}</td><td className="mono">{isoDay(String(row.exit_ts ?? ''))}</td>
        <td>{row.side ?? '—'}</td><td className="r mono">{money(row.quantity, 0)}</td><td className="r mono">{money(row.entry_price)}</td><td className="r mono">{money(row.exit_price)}</td>
        <td className={`r mono ${signTone(typeof row.realized_pnl === 'number' ? row.realized_pnl : null)}`}>{money(row.realized_pnl)}</td>
        <td className={`r mono ${signTone(ret)}`}>{ret === null ? '—' : `${(ret * 100).toFixed(2)}%`}</td></tr>
    })}</tbody>
  </table></div>
}

function Report({ detail }: { detail: RunDetail }) {
  const test = detail.rule_test
  const manifest = detail.manifest as RuleManifest & { reading?: StoredReading; spine?: Spine }
  const figures = useLoad(() => api.figures(detail.run_id), `figures:${detail.run_id}`, 'the chart list')
  if (!test) return <Panel title={detail.display_name}>
    <Empty>The new desk shows rule tests only for now. <a href={workflowHash('results', 'RunDetail', detail.run_id)}>Open this run on the old screen</a>.</Empty>
  </Panel>
  const reading = parseReading(manifest.reading)
  const counts = manifest.reading?.counts
  const tries = counts?.family_trials ?? test.total_trials
  const scored = manifest.spine?.periods?.scored
  const numbers = summaryNumbers(test, manifest, detail.research_gate_watermark)
  const costs = test.fee_bps !== null && test.slippage_bps !== null ? `${test.fee_bps} + ${test.slippage_bps} bps` : '—'
  return <div className="d-report">
    <header className="d-report-head">
      <p className="d-kicker">{test.idea || test.name}</p>
      <h1 className="d-report-rule">{test.rule_sentence || 'The rule words were not stored.'}</h1>
      <div className="d-facts">
        <Fact label="Asset" value={test.symbol ?? '—'} />
        <Fact label="Period" value={`${isoDay(test.first_ts)} → ${isoDay(test.last_ts)}`} />
        <Fact label="Costs per side" value={costs} title={manifest.spine?.costs?.line} />
        <Fact label="Trades" value={numbers[3].value.text} />
        <Fact label="Tries counted" value={tries === null || tries === undefined ? '—' : String(tries)} title={manifest.reading?.count_sentence} />
        <Fact label="Sharpe, scored periods" value={formatNumber(scored?.strategy?.sharpe)} />
        <Fact label="Buy and hold Sharpe" value={formatNumber(scored?.benchmark?.sharpe)} />
      </div>
    </header>
    <Panel title="Reading" className="d-reading" aside={manifest.reading?.evidence?.word ? <span className="d-chip">Evidence: {manifest.reading.evidence.word}</span> : null}>
      {manifest.reading?.sentence ? <p className="d-reading-sentence">{manifest.reading.sentence}</p> : <p className="d-empty">No reading was stored for this test.</p>}
      {manifest.reading?.evidence?.because?.length ? <ul className="d-because">{manifest.reading.evidence.because.map(line => <li key={line}>{line}</li>)}</ul> : null}
      <details className="d-more"><summary>Full reading: checks, aim, measures and counts</summary><div className="d-legacy"><ReadingBlock reading={reading} labels={test.labels} /></div></details>
    </Panel>
    <Panel title="Interactive charts" aside={<span className="d-muted">Drag to pan · wheel to zoom</span>}>
      <DeskChartSurface className="d-tearsheet"><TearSheetStack runId={detail.run_id} /></DeskChartSurface>
    </Panel>
    <Panel title="Worth a look">
      {test.diagnostics?.flags.length ? <ul className="d-flags">{test.diagnostics.flags.map(flag => <li key={flag.flag}><strong>{FLAG_WORDS[flag.flag] ?? flag.flag}</strong><span className="d-muted">{flag.detail}</span></li>)}</ul>
        : <Empty>{test.diagnostics ? 'The diagnostic checks flagged nothing.' : test.diagnostics_reason ?? 'No diagnostics were stored for this test.'}</Empty>}
    </Panel>
    <Panel title="Charts" aside={<span className="d-muted">Click a chart for full screen</span>}>
      {figures.state === 'loading' ? <Skeleton rows={4} height={20} label="Loading the chart list" />
        : figures.state === 'error' ? <Problem>{figures.text}</Problem>
        : figures.value.items.length ? <FigureGallery runId={detail.run_id} items={figures.value.items} />
        : <Empty>No charts were stored for this run.</Empty>}
    </Panel>
    <Panel title="Trades"><TradesTable runId={detail.run_id} /></Panel>
  </div>
}

export function RunReport({ runId }: { runId: string }) {
  const load = useLoad(() => api.run(runId), `run:${runId}`, 'this test')
  if (load.state === 'loading') return <div className="d-report"><Skeleton rows={3} height={26} label="Loading the test" /><Skeleton rows={8} height={16} label="Loading the report" /></div>
  if (load.state === 'error') return <Problem>{load.text}</Problem>
  return <Report detail={load.value} />
}
