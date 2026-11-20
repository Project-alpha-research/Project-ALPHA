import { useId } from 'react'

import { fmtNum, fmtPct } from '../../util/format'
import './CheckCharts.css'
import type { NullTierChart } from './nullChartModel'

// One small picture per tier, all the same size. A tier with 20 draws or more is a histogram; fewer are
// drawn one tick per draw on a number line. The viewBox is the drawn size (300 wide), so type never scales up.

const W = 300
const H = 116
const TOP = 18
const BASE = 80
const SIDE = 8
const span = W - 2 * SIDE

function Marks({ tier }: { tier: NullTierChart }) {
  if (tier.mode === 'strip') {
    return (
      <>
        <line className="cc-axis" x1={SIDE} x2={W - SIDE} y1={BASE} y2={BASE} />
        {tier.ticks.map((t, i) => <line key={i} className="cc-tick" x1={SIDE + t * span} x2={SIDE + t * span} y1={BASE - 26} y2={BASE} />)}
      </>
    )
  }
  const bar = span / tier.heights.length
  return (
    <>
      {tier.heights.map((h, i) => (
        <rect key={i} className="cc-hist" x={SIDE + i * bar + 0.5} y={BASE - h * (BASE - TOP - 10)} width={Math.max(1, bar - 1)} height={Math.max(0, h * (BASE - TOP - 10))} />
      ))}
      <line className="cc-axis" x1={SIDE} x2={W - SIDE} y1={BASE} y2={BASE} />
    </>
  )
}

function Tier({ tier }: { tier: NullTierChart }) {
  const id = useId()
  const markX = SIDE + tier.marker * span
  const right = tier.marker > 0.6
  return (
    <figure className="check-chart-tier">
      <figcaption className="check-chart-tier-name">{tier.title}</figcaption>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-labelledby={id}>
        <title id={id}>{tier.summary}</title>
        <Marks tier={tier} />
        <line className="cc-mark" x1={markX} x2={markX} y1={TOP - 4} y2={BASE} />
        <text x={markX + (right ? -4 : 4)} y={TOP - 6} textAnchor={right ? 'end' : 'start'}>this strategy {fmtNum(tier.observed)}</text>
        <text x={SIDE} y={BASE + 14} className="cc-dim">{fmtNum(tier.low)}</text>
        <text x={W - SIDE} y={BASE + 14} textAnchor="end" className="cc-dim">{fmtNum(tier.high)}</text>
        <text x={W / 2} y={BASE + 14} textAnchor="middle" className="cc-dim">Sharpe of random runs</text>
        <text x={SIDE} y={BASE + 30} className="cc-dim">{tier.roughNote ?? tier.detail}</text>
      </svg>
      {tier.shareAsGood === null ? null : <p className="check-chart-tier-share">Random data did as well in {fmtPct(tier.shareAsGood, 1)} of draws.</p>}
    </figure>
  )
}

export function NullView({ tiers, skipped }: { tiers: NullTierChart[]; skipped: string[] }) {
  const legend = [
    ...(tiers.some((t) => t.mode === 'histogram') ? ['grey bars: how many random runs landed at each Sharpe'] : []),
    ...(tiers.some((t) => t.mode === 'strip') ? ['grey ticks: one for each random run'] : []),
    'blue line: this strategy',
  ]
  return (
    <div className="check-chart">
      <div className="check-chart-tiers">{tiers.map((t) => <Tier key={t.tier} tier={t} />)}</div>
      <ul className="check-chart-legend">{legend.map((text) => <li key={text}>{text}</li>)}</ul>
      {skipped.length ? <p className="muted check-chart-missing">Not drawn, draws or Sharpe not recorded: {skipped.join(', ')}.</p> : null}
    </div>
  )
}
