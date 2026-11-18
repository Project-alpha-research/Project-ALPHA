import { ChartSurface } from '../../theme/ChartSurface'
// Rule-test report — the first section of the report for a run made by `alpha test`: what was
// tested, what is worth a look, the audit, the comparison with buy and hold, nearby variants, the
// years and the macro picture of the worst drawdown. Rows come from `ruleTestModel`; nothing here
// computes a statistic.

import type { RuleTest } from '../../api/types'
import {
  auditRows,
  benchmarkRows,
  labelChips,
  macroRows,
  macroUnavailable,
  NOT_RECORDED,
  testedRows,
  variantRows,
  worstDrawdownLine,
  yearRows,
  type Cell,
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

function YearBar({ share, cell }: { share: number; cell: Cell }) {
  return (
    <td className="rule-test-bar" aria-hidden="true">
      <span className={cell.tone ?? ''} style={{ width: `${Math.round(share * 100)}%` }} />
    </td>
  )
}

export function RuleTestReport({ test }: { test: RuleTest }) {
  const diagnostics = test.diagnostics
  const flags = diagnostics?.flags ?? []
  const audit = auditRows(test)
  const years = yearRows(test)
  const variants = variantRows(test)
  const macro = macroRows(test)
  const macroMissing = macroUnavailable(test)
  const worst = worstDrawdownLine(test)
  const byYear = diagnostics?.by_year
  return (
    <section className="rule-test" aria-label="Rule test">
      <div className="rule-test-col">
      <table className="blotter summary-table rule-test-tested">
        <caption>What was tested</caption>
        <tbody>
          {testedRows(test).map((row) => (
            <tr key={row.label}>
              <td className="k">{row.label}</td>
              <td className={row.mono ? 'mono' : undefined}>{row.value}</td>
            </tr>
          ))}
          <tr>
            <td className="k">Labels</td>
            <td>
              <span className="rule-test-chips">
                {labelChips(test.labels).map((chip) => (
                  <span key={chip.text} className="chip kind" title={chip.title}>{chip.text}</span>
                ))}
              </span>
            </td>
          </tr>
        </tbody>
      </table>

      <table className="blotter summary-table rule-test-flags">
        <caption>Worth a look</caption>
        <tbody>
          {flags.map((flag) => (
            <tr key={flag.flag}>
              <td className="k">{flag.flag.replaceAll('-', ' ')}</td>
              <td>{flag.detail}</td>
            </tr>
          ))}
          {flags.length === 0 ? (
            <tr>
              <td className="muted">
                {diagnostics ? 'The diagnostic pass flagged nothing.' : `Diagnostics ${NOT_RECORDED}: ${test.diagnostics_reason ?? 'no reason stored'}.`}
              </td>
            </tr>
          ) : null}
        </tbody>
      </table>

      {diagnostics ? (
        <>
          <table className="blotter summary-table rule-test-benchmark">
            <caption>Against buy and hold</caption>
            <thead>
              <tr><th /><th className="r">This rule</th><th className="r">Buy and hold</th><th className="r">Difference</th></tr>
            </thead>
            <tbody>
              {benchmarkRows(test).map((row) => (
                <tr key={row.label}>
                  <td className="k">{row.label}</td>
                  <Num cell={row.strategy} />
                  <Num cell={row.benchmark} />
                  <Num cell={row.difference} />
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr><td colSpan={4} className="muted">
                Whole history, not the walk-forward numbers in the summary below. This rule: {diagnostics.full_sample?.basis ?? NOT_RECORDED}. Buy and hold: {diagnostics.benchmark?.basis ?? NOT_RECORDED}.
              </td></tr>
            </tfoot>
          </table>

          <table className="blotter summary-table rule-test-macro">
            <caption>Macro during the worst drawdown</caption>
            {macroMissing ? null : (
              <thead>
                <tr><th>Series</th><th className="r">At start</th><th className="r">At trough</th><th className="r">Change</th></tr>
              </thead>
            )}
            <tbody>
              {worst ? <tr><td className="k">Worst drawdown</td><td colSpan={3} className="mono">{worst}</td></tr> : null}
              {macroMissing ? (
                <tr><td colSpan={4} className="muted">{macroMissing}</td></tr>
              ) : macro.map((row) => (
                <tr key={row.series}>
                  <td className="k mono">{row.series}</td>
                  <Num cell={row.start} />
                  <Num cell={row.trough} />
                  <Num cell={row.change} />
                </tr>
              ))}
            </tbody>
            {macroMissing ? null : (
              <tfoot><tr><td colSpan={4} className="muted">{sentence(diagnostics.macro_window?.basis)}</td></tr></tfoot>
            )}
          </table>
        </>
      ) : null}
      </div>
      {diagnostics ? (
        <div className="rule-test-col">
          <table className="blotter summary-table rule-test-audit">
            <caption>Audit</caption>
            <tbody>
              {audit.map((row) => (
                <tr key={row.check}>
                  <td className="k">{row.check}</td>
                  <td className="rule-test-status"><span className={`chip ${row.chip}`}>{row.status}</span></td>
                  <td>{row.detail}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <table className="blotter summary-table rule-test-variants">
            <caption>If things were slightly different</caption>
            <thead>
              <tr><th>Variant</th><th className="r">Sharpe</th><th className="r">Total return</th><th className="r">Sharpe change</th></tr>
            </thead>
            <tbody>
              {variants.map((row) => (
                <tr key={row.label}>
                  <td className="k">{row.label}</td>
                  <Num cell={row.sharpe} />
                  <Num cell={row.totalReturn} />
                  <Num cell={row.change} />
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr><td colSpan={4} className="muted">
                {sentence(diagnostics.sensitivity?.basis) || NOT_RECORDED}.{variants.filter((row) => row.note).map((row) => ` ${row.label}: ${row.note}.`)}
              </td></tr>
            </tfoot>
          </table>

          <ChartSurface id="rule-test.years">
          <table className="blotter summary-table rule-test-years">
            <caption>By year</caption>
            <thead>
              <tr><th>Year</th><th className="r">This rule</th><th /><th className="r">Buy and hold</th><th /></tr>
            </thead>
            <tbody>
              {years.map((row) => (
                <tr key={row.year}>
                  <td className="k mono">{row.year}</td>
                  <Num cell={row.strategy} />
                  <YearBar share={row.strategyBar} cell={row.strategy} />
                  <Num cell={row.benchmark} />
                  <YearBar share={row.benchmarkBar} cell={row.benchmark} />
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr><td colSpan={5} className="muted">
                Up years: this rule {byYear?.strategy_positive_years ?? NOT_RECORDED}, buy and hold {byYear?.benchmark_positive_years ?? NOT_RECORDED}, of {years.length}. {sentence(byYear?.basis)}
              </td></tr>
            </tfoot>
          </table>
          </ChartSurface>
        </div>
      ) : null}
    </section>
  )
}
