// Rule-test report model — what an `alpha test` run recorded, as rows for the report's first
// section. Pure functions of the server's `rule_test` block (manifest `spine` + diagnostics.json):
// every value is the stored one; a null is shown as `not recorded` with its stored reason. The one
// piece of arithmetic is the display difference between two stored Sharpe values in the
// "slightly different" table (the same kind of display change Market Watch shows).

import type { RuleTest } from '../api/types'
import { isFiniteNum } from '../util/format'

export const NOT_RECORDED = 'not recorded'

export interface Cell {
  text: string
  /** Why the value is missing, from the stored `reasons`; shown as the cell's title. */
  reason: string | null
  tone: 'pos' | 'neg' | null
}

export interface LabelChip {
  text: string
  title: string
}

const LABEL_MEANING: Record<string, string> = {
  'all-in': 'All capital goes into each position; no volatility sizing.',
  quick: 'Quick mode: fewer random-data comparisons and resamples. Treat the statistics as rough.',
  'dev-machine-data': 'Run on the data stored on this development machine.',
  'source-defaulted': 'The asset is in more than one data store; the first match was used.',
  'short-history': 'Less than three years of bars.',
  repeat: 'An identical test was already recorded; it still counts as another trial.',
  'no-diagnostics': 'The diagnostic pass was skipped for this run.',
  error: 'The test ended with an error; unavailable numbers stay empty.',
}

export const RULE_TEST_TITLE =
  'A rule test made by alpha test. It is counted in the trial ledger. It is exploratory: '
  + 'it is not governed research evidence and approves nothing.'

/** The run's labels as small chips, in stored order; an unknown label keeps its own text. */
export function labelChips(labels: readonly string[] | null | undefined): LabelChip[] {
  return (labels ?? []).map((text) => ({ text, title: LABEL_MEANING[text] ?? text }))
}

const missing = (reason: string | null | undefined): Cell => ({
  text: NOT_RECORDED,
  reason: reason ?? null,
  tone: null,
})

/** A stored fraction as a percentage; `signed` adds + and colours by sign. */
export function pct(value: unknown, reason?: string | null, signed = false): Cell {
  if (!isFiniteNum(value)) return missing(reason)
  const text = `${signed && value > 0 ? '+' : ''}${(value * 100).toFixed(1)}%`
  return { text, reason: null, tone: signed ? (value > 0 ? 'pos' : value < 0 ? 'neg' : null) : null }
}

export function ratio(value: unknown, reason?: string | null, signed = false): Cell {
  if (!isFiniteNum(value)) return missing(reason)
  const text = `${signed && value > 0 ? '+' : ''}${value.toFixed(3)}`
  return { text, reason: null, tone: signed ? (value > 0 ? 'pos' : value < 0 ? 'neg' : null) : null }
}

const day = (value: string | null | undefined): string | null =>
  typeof value === 'string' && /^\d{4}-\d{2}-\d{2}/.test(value) ? value.slice(0, 10) : null
const bps = (value: number | null | undefined): string =>
  isFiniteNum(value) ? `${value} bps` : NOT_RECORDED

export interface TestedRow {
  label: string
  value: string
  mono: boolean
}

/** "What was tested": idea, rule, asset, data, period, costs and the trial count. */
export function testedRows(test: RuleTest): TestedRow[] {
  const params = Object.entries(test.rule_params).map(([key, value]) => `${key} ${value}`).join(', ')
  const first = day(test.first_ts)
  const last = day(test.last_ts)
  const bars = isFiniteNum(test.n_bars) ? ` · ${test.n_bars.toLocaleString('en-US')} bars` : ''
  const variants = test.diagnostics?.variants_evaluated
  const trials = isFiniteNum(test.total_trials)
    ? `${test.total_trials} in the ledger when this ran, this one included`
      + (isFiniteNum(variants) ? ` · ${variants} variants also tried` : '')
    : NOT_RECORDED
  return [
    { label: 'Idea', value: test.idea ?? NOT_RECORDED, mono: false },
    {
      label: 'Rule',
      value: test.rule_sentence ?? ([test.rule_kind, params].filter(Boolean).join(': ') || NOT_RECORDED),
      mono: false,
    },
    { label: 'Name', value: test.name ?? NOT_RECORDED, mono: true },
    { label: 'Asset', value: test.symbol ?? NOT_RECORDED, mono: true },
    {
      label: 'Data',
      value: [test.source, test.store ? `store ${test.store}` : null].filter(Boolean).join(' · ') || NOT_RECORDED,
      mono: true,
    },
    { label: 'Period', value: first && last ? `${first} → ${last}${bars}` : NOT_RECORDED, mono: true },
    { label: 'Costs', value: `fee ${bps(test.fee_bps)} · slippage ${bps(test.slippage_bps)}`, mono: true },
    { label: 'Trials', value: trials, mono: true },
    { label: 'Test id', value: test.test_id ?? NOT_RECORDED, mono: true },
  ]
}

export interface AuditRow {
  check: string
  status: string
  /** Existing chip tone: pass, warn (FLAG), or neutral for anything else. */
  chip: 'pass' | 'warn' | 'kind'
  detail: string
}

export function auditRows(test: RuleTest): AuditRow[] {
  return (test.diagnostics?.audit ?? []).map((item) => ({
    check: item.check.replaceAll('-', ' '),
    status: item.status,
    chip: item.status === 'PASS' ? 'pass' : item.status === 'FLAG' ? 'warn' : 'kind',
    detail: item.detail,
  }))
}

export interface CompareRow {
  label: string
  strategy: Cell
  benchmark: Cell
  difference: Cell
}

const METRICS = [
  ['total_return', 'Total return', pct],
  ['cagr', 'Growth per year (CAGR)', pct],
  ['sharpe', 'Sharpe', ratio],
  ['max_drawdown', 'Max drawdown', pct],
] as const

/** Strategy against buy and hold; the difference column is the stored one. */
export function benchmarkRows(test: RuleTest): CompareRow[] {
  const full = test.diagnostics?.full_sample
  const benchmark = test.diagnostics?.benchmark
  const difference = benchmark?.strategy_minus_benchmark
  return METRICS.map(([key, label, format]) => ({
    label,
    strategy: format(full?.[key], full?.reasons[key]),
    benchmark: format(benchmark?.[key], benchmark?.reasons[key]),
    difference: format(difference?.[key], difference?.reasons[key], true),
  }))
}

export interface VariantRow {
  label: string
  sharpe: Cell
  totalReturn: Cell
  change: Cell
  note: string | null
}

const VARIANT_LABEL: Record<string, string> = { costs_x2: 'Costs doubled' }

const sharpeChange = (value: unknown, base: unknown, reason?: string | null): Cell =>
  isFiniteNum(value) && isFiniteNum(base)
    ? ratio(value - base, null, true)
    : missing(reason ?? 'one of the two Sharpe values is not recorded')

/** The as-tested row, each stored variant, then the one-bar delay on its own (surrogate) basis. */
export function variantRows(test: RuleTest): VariantRow[] {
  const diagnostics = test.diagnostics
  const full = diagnostics?.full_sample
  const rows: VariantRow[] = [
    {
      label: 'As tested',
      sharpe: ratio(full?.sharpe, full?.reasons.sharpe),
      totalReturn: pct(full?.total_return, full?.reasons.total_return),
      change: { text: '', reason: null, tone: null },
      note: null,
    },
  ]
  for (const variant of diagnostics?.sensitivity?.variants ?? []) {
    rows.push({
      label: VARIANT_LABEL[variant.name] ?? variant.name.replace('=', ' = '),
      sharpe: ratio(variant.sharpe, variant.reasons.sharpe),
      totalReturn: pct(variant.total_return, variant.reasons.total_return),
      change: sharpeChange(variant.sharpe, full?.sharpe, variant.reasons.sharpe),
      note: null,
    })
  }
  const delay = diagnostics?.delay
  if (delay) {
    const base = ratio(delay.base_sharpe, delay.reasons.base_sharpe)
    rows.push({
      label: 'Trade one bar later',
      sharpe: ratio(delay.delayed_sharpe, delay.reasons.delayed_sharpe),
      totalReturn: { text: '', reason: null, tone: null },
      change: sharpeChange(delay.delayed_sharpe, delay.base_sharpe, delay.reasons.delayed_sharpe),
      note: `approximation; compared with its own base Sharpe ${base.text}`,
    })
  }
  return rows
}

export interface YearRow {
  year: number
  strategy: Cell
  benchmark: Cell
  /** Bar lengths as a share of the largest absolute yearly return shown (drawing scale only). */
  strategyBar: number
  benchmarkBar: number
}

export function yearRows(test: RuleTest): YearRow[] {
  const years = test.diagnostics?.by_year?.years ?? []
  const scale = Math.max(
    0,
    ...years.flatMap((row) => [row.strategy_return, row.benchmark_return])
      .filter(isFiniteNum)
      .map(Math.abs),
  )
  const bar = (value: unknown): number => (isFiniteNum(value) && scale > 0 ? Math.abs(value) / scale : 0)
  return years.map((row) => ({
    year: row.year,
    strategy: pct(row.strategy_return, null, true),
    benchmark: pct(row.benchmark_return, null, true),
    strategyBar: bar(row.strategy_return),
    benchmarkBar: bar(row.benchmark_return),
  }))
}

export interface MacroRow {
  series: string
  start: Cell
  trough: Cell
  change: Cell
}

const plain = (value: unknown, reason: string | null, signed = false): Cell =>
  isFiniteNum(value)
    ? {
        text: `${signed && value > 0 ? '+' : ''}${value.toFixed(2)}`,
        reason: null,
        tone: null,
      }
    : missing(reason)

export function macroRows(test: RuleTest): MacroRow[] {
  return (test.diagnostics?.macro_window?.series ?? []).map((row) => ({
    series: row.series_id,
    start: plain(row.start_value, row.reason),
    trough: plain(row.trough_value, row.reason),
    change: plain(row.change, row.reason, true),
  }))
}

/** One line for the macro section when no window is stored, with the stored reason. */
export function macroUnavailable(test: RuleTest): string | null {
  const macro = test.diagnostics?.macro_window
  if (macro?.available) return null
  return `Not available: ${macro?.reason ?? test.diagnostics_reason ?? 'no macro window recorded'}.`
}

/** `start → trough` of the worst stored drawdown with its depth, or null. */
export function worstDrawdownLine(test: RuleTest): string | null {
  const worst = test.diagnostics?.worst_drawdown
  const start = day(worst?.start)
  const trough = day(worst?.trough)
  if (!worst || !start || !trough) return null
  return `${start} → ${trough} · strategy ${pct(worst.depth).text} · buy and hold ${pct(worst.benchmark_return).text}`
}
