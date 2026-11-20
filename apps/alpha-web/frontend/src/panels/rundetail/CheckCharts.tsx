import type { ReactNode } from 'react'

import { fmtNum } from '../../util/format'
import './CheckCharts.css'
import { Legend } from './chartParts'
import { useWidth } from './useChartWidth'
import type { CpcvChart, DsrChart, IntervalChart } from './checkChartModel'

// Presentational parts only: every position and word comes from `checkChartModel.ts`.

const clampX = (x: number, lo: number, hi: number): number => Math.max(lo, Math.min(hi, x))

// ---- number line (bootstrap interval, cross-validation) -----------------------------------

interface LineProps {
  label: string
  zero: number
  bar: [number, number]
  dot: number
  dotText: string
  barTexts: [string, string]
  barName: string
  dotName: string
}

function NumberLine({ label, zero, bar, dot, dotText, barTexts, barName, dotName, note }: LineProps & { note?: string }) {
  const [ref, width] = useWidth()
  const pad = 28
  const px = (x: number): number => pad + x * (width - 2 * pad)
  const mid = 44
  return (
    <figure className="check-chart">
      <div ref={ref}>
        <svg width={width} height={88} viewBox={`0 0 ${width} 88`} role="img" aria-label={label}>
          <line className="cc-axis" x1={pad} x2={width - pad} y1={mid} y2={mid} />
          <line className="cc-zero" x1={px(zero)} x2={px(zero)} y1={24} y2={68} />
          <text x={px(zero)} y={82} textAnchor="middle">zero</text>
          <rect className="cc-bar" x={px(bar[0])} y={mid - 7} width={Math.max(2, px(bar[1]) - px(bar[0]))} height={14} />
          <text x={clampX(px(bar[0]), 18, width - 18)} y={mid + 24} textAnchor="end" className="cc-dim">{barTexts[0]}</text>
          <text x={clampX(px(bar[1]), 18, width - 18)} y={mid + 24} textAnchor="start" className="cc-dim">{barTexts[1]}</text>
          <circle className="cc-dot" cx={px(dot)} cy={mid} r={5.5} />
          <text x={clampX(px(dot), 40, width - 40)} y={16} textAnchor="middle">{dotText}</text>
        </svg>
      </div>
      <Legend items={[{ cls: 'test', text: barName }, { text: `dot: ${dotName}` }, { text: 'dashed line: zero' }]} />
      {note ? <p className="muted check-chart-missing">{note}</p> : null}
    </figure>
  )
}

export function IntervalView({ chart }: { chart: IntervalChart }) {
  return (
    <NumberLine label={chart.summary} zero={chart.zero} bar={[chart.lower, chart.upper]} dot={chart.point}
      dotText={`Sharpe ${fmtNum(chart.values.point)}`} barTexts={[fmtNum(chart.values.lower), fmtNum(chart.values.upper)]}
      barName={`bar: ${chart.confidencePct} interval`} dotName="this strategy's Sharpe" />
  )
}

export function CpcvView({ chart }: { chart: CpcvChart }) {
  return (
    <NumberLine label={chart.summary} zero={chart.zero} bar={[chart.low, chart.high]} dot={chart.mean} dotText={`mean ${fmtNum(chart.values.mean)}`}
      barTexts={[fmtNum(chart.values.low), fmtNum(chart.values.high)]} barName={chart.barName} dotName="mean Sharpe across splits" note={chart.note} />
  )
}

// ---- deflated Sharpe ----------------------------------------------------------------------

export function DsrView({ chart }: { chart: DsrChart }): ReactNode {
  const [ref, width] = useWidth()
  const pad = 6
  const px = (x: number): number => pad + x * (width - 2 * pad)
  return (
    <figure className="check-chart" aria-label={chart.summary}>
      <div className="check-chart-rows" ref={ref} role="img" aria-label={chart.summary}>
        {chart.bars.map((bar, i) => (
          <div key={bar.label}>
            <p className="check-chart-row-label">
              {bar.label}, per trading period: <span className="num">{bar.perPeriod}</span>
              {bar.perYear === null ? null : <> (per year: <span className="num">{bar.perYear}</span>)</>}
            </p>
            <svg width={width} height={22} viewBox={`0 0 ${width} 22`} aria-hidden="true">
              <rect className={i === 0 ? 'cc-self' : 'cc-luck'} x={Math.min(px(bar.from), px(bar.to))} y={3} width={Math.max(1.5, Math.abs(px(bar.to) - px(bar.from)))} height={16} />
              <line className="cc-zero" x1={px(chart.zero)} x2={px(chart.zero)} y1={0} y2={22} />
            </svg>
          </div>
        ))}
      </div>
      <p className="muted check-chart-missing">Dashed line: zero. {chart.unitNote}</p>
      {chart.probabilityNote ? <p className="muted check-chart-missing">{chart.probabilityNote}</p> : null}
    </figure>
  )
}
