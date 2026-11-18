import type { FigureCatalogueItem, RuleTest } from '../../api/types'
import { FigureCard } from '../../components/FigureCard'
import { GLOSSARY } from '../../explain/glossary'
import type { RecordedManifest } from '../../explain/verdictStory'
import {
  auditRows, labelChips, NOT_RECORDED, quickCaveat, ratio, summaryFigures, summaryHeadline, summaryNumbers,
  testedRows, variantRows, type Cell,
} from '../ruleTestModel'

/** A stored basis note shown as a sentence: first letter upper-case; the words are unchanged. */
function sentence(text: string | null | undefined): string {
  return text ? text.charAt(0).toUpperCase() + text.slice(1) : ''
}

function Num({ cell }: { cell: Cell }) {
  const missing = cell.text === NOT_RECORDED
  return (
    <td className={`num mono${cell.tone ? ` ${cell.tone}` : ''}${missing ? ' muted' : ''}`} title={cell.reason ?? undefined}>
      {cell.text}
      {missing && cell.reason ? <span className="rule-test-reason">{cell.reason}</span> : null}
    </td>
  )
}

const FLAG_LABELS: Record<string, string> = {
  'below-benchmark': 'Holding the market had a higher risk-adjusted score.',
  'drawdown-with-market': 'The market also fell during the rule’s worst drop.',
  'concentrated-profit': 'A few trades accounted for most of the profit.',
  'fragile-to-costs': 'The result was sensitive to trading costs.',
  'fragile-to-parameters': 'Changing the rule settings affected the result.',
  'fragile-to-delay': 'Trading later reduced the risk-adjusted score.',
  'fragile-to-price-noise': 'Small price changes affected the result.',
  'implausibly-good': 'The result looks unusually strong.',
}

interface Props {
  test: RuleTest
  manifest: RecordedManifest
  runId: string
  runName?: string
  figures: FigureCatalogueItem[] | null
  watermark?: string | null
  figureError?: string
}

export function RuleTestReport({ test, manifest, runId, runName, figures, figureError, watermark }: Props) {
  const diagnostics = test.diagnostics
  const flags = diagnostics?.flags ?? []
  const audit = auditRows(test)
  const variants = variantRows(test)
  const charts = summaryFigures(figures ?? [])
  const ruleSharpe = ratio(diagnostics?.full_sample?.sharpe, diagnostics?.full_sample?.reasons.sharpe)
  const holdSharpe = ratio(diagnostics?.benchmark?.sharpe, diagnostics?.benchmark?.reasons.sharpe)
  const quick = quickCaveat(test)
  return (
    <section className="rule-test" aria-label="Rule test">
      <h2>{summaryHeadline(test)}</h2>
      <div className="metric-grid" role="group" aria-label="Results over the full history">
        {summaryNumbers(test, manifest, watermark).map(row => (
          <div className="metric" key={row.label}>
            <span title={row.gloss}>{row.label}</span>
            <strong className="metric-val mono">{row.value.text}</strong>
            {row.value.reason && <small className="muted">{row.value.reason}</small>}
            {row.caveats.map(note => note && <small key={note} className="muted">{note}</small>)}
          </div>
        ))}
      </div>
      <div>
        <p><strong>Risk-adjusted score (Sharpe)</strong> over the full history · Rule{' '}
          <span className="mono" title={ruleSharpe.reason ?? undefined}>{ruleSharpe.text}</span>
          {' · '}Buy and hold <span className="mono" title={holdSharpe.reason ?? undefined}>{holdSharpe.text}</span></p>
        <small>{GLOSSARY.sharpe.short}</small>
        {quick && <p className="muted">{quick}</p>}
      </div>
      {figureError ? <p role="alert">Could not load the chart list. {figureError}</p>
        : figures === null ? <p role="status">Loading charts…</p>
        : charts.length ? <div>
          <p>Charts cover the scored test period. The numbers above cover the full history.</p>
          {charts.map(item => (
            <FigureCard key={item.figure_id} item={item} runId={runId} runName={runName} />
          ))}
        </div> : <p className="muted">no chart stored for this run</p>}

      <table className="blotter summary-table">
        <caption>Worth a look</caption>
        <tbody>
          {flags.map(flag => (
            <tr key={flag.flag}>
              <td title={flag.flag}>{FLAG_LABELS[flag.flag] ?? flag.detail}</td>
              {FLAG_LABELS[flag.flag] && <td>{flag.detail}</td>}
            </tr>
          ))}
          {!flags.length && <tr><td className="muted">{diagnostics ? 'The diagnostic pass flagged nothing.'
            : test.diagnostics_reason ?? 'Diagnostics not recorded.'}</td></tr>}
        </tbody>
      </table>

      <table className="blotter summary-table">
        <caption>If things were slightly different</caption>
        <thead><tr><th>Variant</th><th className="r" title={GLOSSARY.sharpe.short}>Sharpe</th>
          <th className="r" title={GLOSSARY.total_return.short}>Total return</th>
          <th className="r" title="Difference from the risk-adjusted score for the original settings.">Sharpe change</th></tr></thead>
        <tbody>
          {diagnostics ? variants.map(row => (
            <tr key={row.label}><td className="k">{row.label}</td><Num cell={row.sharpe} />
              <Num cell={row.totalReturn} /><Num cell={row.change} /></tr>
          )) : <tr><td colSpan={4}>{NOT_RECORDED}</td></tr>}
        </tbody>
        {diagnostics && <tfoot><tr><td colSpan={4} className="muted">
          {sentence(diagnostics.sensitivity?.basis) || NOT_RECORDED}.{variants.filter(row => row.note).map(row => ` ${row.label}: ${row.note}.`)}
        </td></tr></tfoot>}
      </table>

      <details><summary>What was tested</summary>
        <table className="blotter summary-table rule-test-tested"><tbody>
          {testedRows(test).map(row => (
            <tr key={row.label}><td className="k">{row.label}</td><td className={row.mono ? 'mono' : undefined}>
              {row.label === 'Idea' && !test.idea?.trim() ? <small>{row.value}</small> : row.value}
            </td></tr>
          ))}
          <tr><td className="k">Labels</td><td><span className="rule-test-chips">
            {labelChips(test.labels).map(chip => <span key={chip.text} className="chip kind" title={chip.title}>{chip.text}</span>)}
          </span></td></tr>
        </tbody></table>
      </details>
      <details><summary>Checks on the test itself</summary>
        {audit.length ? <table className="blotter summary-table"><tbody>
          {audit.map(row => (
            <tr key={row.id}><td className="k">{row.check}</td>
              <td className="rule-test-status"><span className={`chip ${row.chip}`}>{row.status}</span></td>
              <td>{row.detail} <small className="muted mono">{row.id}</small></td></tr>
          ))}
        </tbody></table> : <p>{test.diagnostics_reason ?? 'No checks were recorded.'}</p>}
      </details>
    </section>
  )
}
