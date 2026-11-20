import { useId } from 'react'

import { fmtNum, fmtPct } from '../../util/format'
import './CheckCharts.css'
import type { NullTierChart } from './nullChartModel'

const W = 220
const H = 96
const TOP = 16
const BASE = 76

function Tier({ tier }: { tier: NullTierChart }) {
  const id = useId()
  const gap = 1
  const n = tier.heights.length
  const bar = (W - 2 * 6) / n
  const markX = 6 + tier.marker * (W - 12)
  const right = tier.marker > 0.6
  return (
    <figure className="check-chart-tier">
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-labelledby={id}>
        <title id={id}>{tier.summary}</title>
        {tier.heights.map((h, i) => (
          <rect key={i} className="cc-hist" x={6 + i * bar + gap / 2} y={BASE - h * (BASE - TOP - 8)} width={Math.max(1, bar - gap)} height={Math.max(0, h * (BASE - TOP - 8))} />
        ))}
        <line className="cc-axis" x1={6} x2={W - 6} y1={BASE} y2={BASE} />
        <line className="cc-mark" x1={markX} x2={markX} y1={TOP - 4} y2={BASE} />
        <text x={markX + (right ? -4 : 4)} y={TOP - 5} textAnchor={right ? 'end' : 'start'}>this strategy {fmtNum(tier.observed)}</text>
        <text x={6} y={BASE + 13} className="cc-dim">{fmtNum(tier.low)}</text>
        <text x={W - 6} y={BASE + 13} textAnchor="end" className="cc-dim">{fmtNum(tier.high)}</text>
        <text x={W / 2} y={BASE + 13} textAnchor="middle" className="cc-dim">Sharpe of random runs</text>
      </svg>
      <figcaption>
        {tier.title}.{tier.shareAsGood === null ? '' : ` Random data did as well in ${fmtPct(tier.shareAsGood, 1)} of draws.`}
      </figcaption>
    </figure>
  )
}

export function NullView({ tiers, skipped }: { tiers: NullTierChart[]; skipped: string[] }) {
  return (
    <div className="check-chart">
      <div className="check-chart-tiers">{tiers.map((t) => <Tier key={t.tier} tier={t} />)}</div>
      <ul className="check-chart-legend">
        <li>grey bars: how many random runs landed at each Sharpe</li>
        <li>blue line: this strategy</li>
      </ul>
      {skipped.length ? <p className="muted check-chart-missing">Not drawn, draws or Sharpe not recorded: {skipped.join(', ')}.</p> : null}
    </div>
  )
}
