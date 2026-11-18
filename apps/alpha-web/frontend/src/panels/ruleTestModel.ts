// Formats the run's stored facts. Only the variants table subtracts two recorded scores.

import type { FigureCatalogueItem, RuleTest } from '../api/types'
import { GLOSSARY } from '../explain/glossary'
import { sparseTradeStory, type RecordedManifest } from '../explain/verdictStory'
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
  exploratory: 'Exploratory test. These results describe this run only.',
  'too-few-trades': 'Too few closed trades in the walk-forward test to judge the result.',
  'benchmark-price-only': 'Both lines use prices only. No dividend cash was recorded.',
  'all-in': 'All capital goes into each position; no volatility sizing.',
  quick: 'Quick mode used fewer random comparisons to check the result.',
  'data-health-pass': 'The data checks found no fault. The prices can still be wrong.',
  'data-health-warn': 'A data check found a warning. Read the finding before using this result.',
  'data-health-fail': 'A data check found a fault in the prices or their supporting records.',
  'data-health-unchecked': 'At least one series has no current data health report.',
  'data-health-overridden': 'The run records why it proceeded after a failed data check.',
  'dev-machine-data': 'Run on the data stored on this development machine.',
  'source-defaulted': 'The asset is in more than one data store; the first match was used.',
  'short-history': 'The test covers less than three years of price history.',
  repeat: 'An identical test was already recorded; it still counts as another trial.',
  'no-diagnostics': 'The diagnostic pass was skipped for this run.',
  error: 'The test ended with an error; unavailable numbers stay empty.',
}

export const RULE_TEST_TITLE =
  'A rule test made by alpha test. It is counted in the trial ledger. It is exploratory: '
  + 'it is not governed research evidence and approves nothing.'

/** The run's labels as small chips, in stored order; an unknown label keeps its own text. */
export function labelChips(labels: readonly string[] | null | undefined): LabelChip[] {
  return (labels ?? []).map((text) => ({ text, title: LABEL_MEANING[text] ?? `No explanation was saved for the label “${text}”.` }))
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
    { label: 'Idea', value: test.idea?.trim() || 'no idea text was saved with this run', mono: false },
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
  id: string
  check: string
  status: string
  /** Existing chip tone: pass, warn (FLAG), or neutral for anything else. */
  chip: 'pass' | 'warn' | 'kind'
  detail: string
}

const CHECK_LABELS: Record<string, string> = {
  'fills-after-decisions': 'Did each trade follow its decision?',
  'fills-inside-bar-range': 'Were trade prices within the market range?',
  'costs-charged': 'Did the test include trading costs?',
  'enough-trades': 'Were there enough closed trades?',
  'benchmark-present': 'Was there a buy-and-hold comparison?',
  'history-length': 'Did the test cover at least three years?',
  'artifacts-intact': 'Did the saved files pass verification?',
  'quick-run': 'Did the test use the full set of checks?',
  'variants-counted': 'Did the trial count include the other settings tested?',
}

export function auditRows(test: RuleTest): AuditRow[] {
  return (test.diagnostics?.audit ?? []).map((item) => ({
    id: item.check,
    check: CHECK_LABELS[item.check] ?? item.check.replaceAll('-', ' '),
    status: item.status,
    chip: item.status === 'PASS' ? 'pass' : item.status === 'FLAG' ? 'warn' : 'kind',
    detail: item.detail,
  }))
}

function comparisonWording(difference: number | null | undefined): string {
  if (!isFiniteNum(difference)) return 'compared with'
  if (difference > 0) return 'ahead of'
  if (difference < 0) return 'behind'
  return 'level with'
}

type Metrics = Partial<NonNullable<NonNullable<RuleTest['diagnostics']>['full_sample']>>
export type SummaryPeriod = 'tradable' | 'scored'

export interface PeriodResult {
  first_ts?: string
  last_ts?: string
  price_basis?: string
  strategy?: Metrics | null
  benchmark?: Metrics | null
  relative_return?: number | null
}

export function healthLine(health?: { verdict?: unknown; sentence?: unknown } | null): string | null {
  if (health?.verdict === 'pass') return null
  return typeof health?.sentence === 'string' ? health.sentence : 'Data health: not recorded.'
}

export type RuleManifest = RecordedManifest & {
  data_health?: { verdict: string; sentence: string }
  spine?: { periods?: Partial<Record<SummaryPeriod, PeriodResult>> }
}

export function dateRange(first?: string | null, last?: string | null): string {
  return day(first) && day(last) ? `${day(first)} to ${day(last)}` : NOT_RECORDED
}

export function summaryHeadline(test: RuleTest, row?: PeriodResult): string {
  const words = test.idea?.trim() || test.rule_sentence?.trim()
  const rule = words ? `“${words}”` : 'This rule'
  const market = test.symbol ? ` on ${test.symbol}` : ''
  const result = row?.strategy?.total_return
  const hold = row?.benchmark?.total_return
  const subject = `${rule}${market} could trade from ${dateRange(row?.first_ts, row?.last_ts)}`
  if (isFiniteNum(result)) {
    const wording = comparisonWording(row?.relative_return)
    const comparison = isFiniteNum(hold)
      ? `${wording} ${pct(hold).text} for simply holding the market`
      : 'but the buy-and-hold return is unavailable'
    return `${subject}. It returned ${pct(result).text} after costs, ${comparison}.`
  }
  if (isFiniteNum(hold)) return `${subject}. It has no saved rule return, while holding the market returned ${pct(hold).text}.`
  return `${subject}. Return comparison: ${NOT_RECORDED}.`
}

export function summaryFigures(items: FigureCatalogueItem[], period?: SummaryPeriod) {
  const ids = ['equity_vs_passive', 'equity_underwater']
  const tradable = ids.map(id => 'tradable_' + id)
  const wanted = period === 'tradable' ? tradable : period === 'scored' ? ids : [...tradable, ...ids]
  return wanted.flatMap(id => items.filter(item => item.figure_id === id && item.available))
}

export function summaryNumbers(test: RuleTest, manifest: RuleManifest, watermark?: string | null, period: SummaryPeriod = 'tradable') {
  const row = manifest.spine?.periods?.[period]
  const full = row?.strategy
  const hold = row?.benchmark
  const labels = test.labels
  const flagged = (id: string) => test.diagnostics?.audit.some(check => check.check === id && check.status === 'FLAG')
  const short = labels.includes('short-history') || flagged('history-length') ? LABEL_MEANING['short-history'] : null
  const data = labels.includes('dev-machine-data') ? LABEL_MEANING['dev-machine-data'] : null
  const cap = sparseTradeStory({ ...manifest, labels: [...(manifest.labels ?? []), ...labels] })
  const tradeCaveat = cap ? `The grade counts trades in the walk-forward test periods held back for scoring. ${cap}`
    : flagged('enough-trades') ? LABEL_MEANING['too-few-trades'] : null
  return [
    { label: 'Total return after costs', gloss: GLOSSARY.total_return.short,
      value: pct(full?.total_return, full?.reasons?.total_return),
      caveats: [row?.price_basis ?? NOT_RECORDED, watermark || (labels.includes('exploratory') ? LABEL_MEANING.exploratory : null), data] },
    { label: 'Return per year', gloss: GLOSSARY.cagr.short, value: pct(full?.cagr, full?.reasons?.cagr), caveats: [short] },
    { label: 'Worst drop', gloss: GLOSSARY.max_drawdown.short,
      value: pct(full?.max_drawdown, full?.reasons?.max_drawdown), caveats: [short] },
    { label: 'Closed trades', gloss: 'Positions opened and closed during this period.',
      value: isFiniteNum(full?.trades) ? { text: String(full.trades), reason: null } : missing(full?.reasons?.trades),
      caveats: [tradeCaveat] },
    { label: 'Buy-and-hold return', gloss: 'Return from holding the market over the same bars, before trading costs.',
      value: pct(hold?.total_return, hold?.reasons?.total_return), caveats: [row?.price_basis ?? NOT_RECORDED, data] },
  ]
}

export function quickCaveat(test: RuleTest): string | null {
  return test.labels.includes('quick') || test.diagnostics?.audit.some(row => row.check === 'quick-run' && row.status === 'FLAG')
    ? LABEL_MEANING.quick : null
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
      sharpe: ratio(full?.sharpe, full?.reasons?.sharpe),
      totalReturn: pct(full?.total_return, full?.reasons?.total_return),
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
