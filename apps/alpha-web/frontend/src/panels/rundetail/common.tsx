// Shared building blocks for the Run Detail tabs: sections, metric grids, and the ExplainCard —
// the one component that renders any Explained story in the active explanation mode
// (narrative teaches, terse annotates; the toggle lives in state/settings).

import type { ReactNode } from 'react'

import { StateIcon } from '../../components/StateIcon'
import { Term } from '../../components/Term'
import type { Explained, GateStory, StatChip, Suggestion } from '../../explain/types'
import { useSettings } from '../../state/settings'
import { asNum, fmtNum, fmtPct } from '../../util/format'
import { STATE_WORDS } from '../readingModel'
import type { Dict } from './commonUtils'

export function Section({ title, children, right }: { title: string; children: ReactNode; right?: ReactNode }) {
  return (
    <section className="rd-section">
      <div className="rd-head">
        {title}
        {right ? <span className="rd-head-right">{right}</span> : null}
      </div>
      {children}
    </section>
  )
}

const METRIC_LABEL: Record<string, { label: string; term?: string; pct?: boolean }> = {
  sharpe: { label: 'Sharpe', term: 'sharpe' },
  cagr: { label: 'CAGR', term: 'cagr', pct: true },
  annualized_vol: { label: 'Ann. Vol', term: 'annualized_vol', pct: true },
  max_drawdown: { label: 'Max DD', term: 'max_drawdown', pct: true },
  total_return: { label: 'Total Return', term: 'total_return', pct: true },
  value_at_risk: { label: 'VaR 95%', term: 'value_at_risk', pct: true },
  expected_shortfall: { label: 'ES 95%', term: 'expected_shortfall', pct: true },
  risk_of_ruin: { label: 'Risk of Ruin', term: 'risk_of_ruin', pct: true },
}

export function Metric({
  label,
  value,
  digits = 2,
  pct = false,
  term,
}: {
  label: string
  value: unknown
  digits?: number
  pct?: boolean
  term?: string
}) {
  const v = asNum(value)
  if (v === null) return null
  const name = term ? <Term k={term}>{label}</Term> : label
  return (
    <div className="metric">
      <span className="eyebrow">{name}</span>
      <span className={`metric-val num${v < 0 ? ' neg' : ''}`}>{pct ? fmtPct(v, 1) : fmtNum(v, digits)}</span>
    </div>
  )
}

export function MetricGrid({ metrics }: { metrics: Dict }) {
  const entries = Object.entries(metrics).filter(([, v]) => asNum(v) !== null)
  if (entries.length === 0) return null
  return (
    <div className="metric-grid">
      {entries.map(([k, v]) => {
        const meta = METRIC_LABEL[k]
        return (
          <Metric
            key={k}
            label={meta?.label ?? k}
            term={meta?.term}
            pct={meta?.pct ?? false}
            value={v}
            digits={2}
          />
        )
      })}
    </div>
  )
}

export function StatChips({ stats }: { stats: StatChip[] }) {
  if (!stats.length) return null
  return (
    <div className="stat-chips">
      {stats.map((s, i) => (
        <span className="stat-chip" key={i}>
          <span className="eyebrow">{s.term ? <Term k={s.term}>{s.label}</Term> : s.label}</span>
          <span className="num">{s.value}</span>
        </span>
      ))}
    </div>
  )
}

/**
 * Any Explained story as a card: stats and the active voice. A fact check keeps its state word beside its title (the icon and
 * the word, never colour alone). A statistic shows its numbers; the level the old grade used is one muted line. Never passed or failed.
 */
export function ExplainCard({
  story,
  title,
  stats = [],
  tests,
}: {
  story: Explained & Partial<Pick<GateStory, 'state' | 'oldLevel' | 'plain'>>
  title: string
  stats?: StatChip[]
  tests?: string
}) {
  const { explain } = useSettings()
  return (
    <div className={`explain-card tone-${story.tone}`}>
      <div className="explain-head">
        {story.state ? (
          <span className="explain-state" data-state={story.state}>
            <StateIcon state={story.state} />
            <strong>{story.state === 'sound' ? 'computed' : STATE_WORDS[story.state]}</strong>
          </span>
        ) : null}
        <span className="explain-title">{title}</span>
        {story.state === 'sound' ? <span className="muted explain-state-hint">computed means the check could run; it does not say the result is good</span> : null}
      </div>
      {explain === 'narrative' && story.plain ? <p className="explain-plain">{story.plain}</p> : null}
      <StatChips stats={stats} />
      {story.oldLevel ? <p className="muted explain-old-level">{story.oldLevel}</p> : null}
      {explain === 'narrative' ? (
        <details className="explain-how">
          <summary>How this check works</summary>
          {tests ? <p className="explain-tests">{tests}</p> : null}
          <p className="explain-narrative">{story.narrative}</p>
        </details>
      ) : (
        <p className="explain-terse mono">{story.terse}</p>
      )}
    </div>
  )
}

export function SuggestionList({
  items,
  onLaunch,
}: {
  items: Suggestion[]
  onLaunch?: (command: string, args: string) => void
}) {
  const { explain } = useSettings()
  if (!items.length) return null
  return (
    <div className="suggestions">
      {items.map((s, i) => (
        <div className="suggestion" key={i}>
          <div className="suggestion-title">
            <span className="suggestion-marker">→</span> {s.title}
          </div>
          {explain === 'narrative' ? <p className="suggestion-why">{s.why}</p> : null}
          {s.action && onLaunch ? (
            <button className="btn" onClick={() => onLaunch(s.action!.command, s.action!.args)}>
              ▶ alpha {s.action.command} {s.action.args}
            </button>
          ) : null}
        </div>
      ))}
    </div>
  )
}
