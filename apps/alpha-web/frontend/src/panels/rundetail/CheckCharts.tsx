import { useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react'

import { fmtNum } from '../../util/format'
import './CheckCharts.css'
import type { CpcvChart, DsrChart, IntervalChart, NotRecorded, WalkForward } from './checkChartModel'

// Presentational parts only: every position and word comes from `checkChartModel.ts`.

export function ChartNote({ text }: { text: string }) {
  return <p className="muted check-chart-missing">{text}</p>
}
export const NotAvailable = ({ model }: { model: NotRecorded }) => <ChartNote text={`Chart not available: ${model.reason}.`} />

/** Width of the box the chart sits in, kept in step with the window. 560 until measured. */
function useWidth(): [React.RefObject<HTMLDivElement | null>, number] {
  const ref = useRef<HTMLDivElement>(null)
  const [width, setWidth] = useState(560)
  useLayoutEffect(() => {
    const element = ref.current
    if (!element) return
    const measure = () => setWidth(Math.max(240, Math.min(760, Math.floor(element.clientWidth) || 560)))
    measure()
    const watcher = new ResizeObserver(measure)
    watcher.observe(element)
    return () => watcher.disconnect()
  }, [])
  return [ref, width]
}

function Legend({ items }: { items: { cls?: string; text: string }[] }) {
  return (
    <ul className="check-chart-legend">
      {items.map((item) => (
        <li key={item.text}>{item.cls ? <span className={`check-chart-swatch ${item.cls}`} aria-hidden="true" /> : null}{item.text}</li>
      ))}
    </ul>
  )
}

const clampX = (x: number, lo: number, hi: number): number => Math.max(lo, Math.min(hi, x))

// ---- walk-forward ------------------------------------------------------------------------

const LEFT = 46
const PRICE_TOP = 6
const PRICE_BOTTOM = 86
const WARM_Y = 92
const TEST_Y = 106
const TEST_H = 18
const AXIS_Y = 140
const MIN_BAND_PX = 26

export function WalkForwardView({ chart }: { chart: WalkForward }) {
  const [ref, measured] = useWidth()
  const patternId = `cc-hatch-${useId().replaceAll(':', '')}`
  const width = Math.max(measured, LEFT + chart.testBands.length * MIN_BAND_PX + 8)
  const plot = width - LEFT - 6
  const px = (x: number): number => LEFT + x * plot
  const py = (y: number): number => PRICE_BOTTOM - y * (PRICE_BOTTOM - PRICE_TOP)
  const line = chart.price.map((p) => `${px(p.x).toFixed(1)},${py(p.y).toFixed(1)}`).join(' ')
  return (
    <figure className="check-chart">
      <div className="check-chart-scroll" ref={ref}>
        <svg width={width} height={150} viewBox={`0 0 ${width} 150`} role="img" aria-label={chart.summary}>
          <defs>
            <pattern id={patternId} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
              <line x1="0" y1="0" x2="0" y2="5" className="cc-warm" />
            </pattern>
          </defs>
          {chart.testBands.map((b) => (
            <rect key={`s${b.fold}`} className="cc-test" x={px(b.x0)} y={PRICE_TOP} width={Math.max(1, px(b.x1) - px(b.x0))} height={PRICE_BOTTOM - PRICE_TOP} />
          ))}
          {line ? <polyline className="cc-price" points={line} /> : null}
          {chart.priceHigh !== null && chart.priceLow !== null ? (
            <>
              <text x={LEFT - 4} y={PRICE_TOP + 9} textAnchor="end" className="cc-dim">{fmtNum(chart.priceHigh, 0)}</text>
              <text x={LEFT - 4} y={PRICE_BOTTOM} textAnchor="end" className="cc-dim">{fmtNum(chart.priceLow, 0)}</text>
            </>
          ) : (
            <text x={LEFT} y={PRICE_TOP + 40} className="cc-dim">{chart.priceNote}</text>
          )}
          {chart.trainBands.map((b) => (
            <rect key={`w${b.x0}`} x={px(b.x0)} y={WARM_Y} width={Math.max(1, px(b.x1) - px(b.x0))} height={10} fill={`url(#${patternId})`} className="cc-warm" />
          ))}
          <text x={LEFT + 2} y={WARM_Y + 8} className="cc-dim cc-halo" fontSize="9">{chart.trainLabel}</text>
          {chart.testBands.map((b) => (
            <g key={`t${b.fold}`}>
              <rect className="cc-test-strip" x={px(b.x0)} y={TEST_Y} width={Math.max(1, px(b.x1) - px(b.x0))} height={TEST_H}>
                <title>{`tested window ${b.fold + 1}: Sharpe ${b.sharpe === null ? 'not recorded' : fmtNum(b.sharpe)}`}</title>
              </rect>
              {b.sharpe !== null && px(b.x1) - px(b.x0) >= MIN_BAND_PX - 2 ? (
                <text x={(px(b.x0) + px(b.x1)) / 2} y={TEST_Y + 13} textAnchor="middle" fontSize="10">{fmtNum(b.sharpe, 1)}</text>
              ) : null}
            </g>
          ))}
          {chart.overlaps.map((o) => (
            <rect key={`o${o.fold}`} className="cc-overlap" x={px(o.x0)} y={PRICE_TOP} width={Math.max(2, px(o.x1) - px(o.x0))} height={TEST_Y + TEST_H - PRICE_TOP} />
          ))}
          <text x={LEFT} y={AXIS_Y + 6}>{new Date(chart.t0).toISOString().slice(0, 10)}</text>
          <text x={width - 6} y={AXIS_Y + 6} textAnchor="end">{new Date(chart.t1).toISOString().slice(0, 10)}</text>
        </svg>
      </div>
      <Legend items={[
        { text: 'line: price of this asset (stored bars between the run\u2019s first and last date)' },
        { cls: 'warm', text: chart.trainLabel },
        { cls: 'test', text: 'tested here, not seen before (number: out-of-sample Sharpe)' },
        ...(chart.warning ? [{ cls: 'warn', text: chart.warning }] : []),
      ]} />
      {chart.warning ? <p className="check-chart-warning">Warning: {chart.warning}. The yellow band marks the shared dates.</p> : null}
    </figure>
  )
}

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
      barTexts={[fmtNum(chart.values.low), fmtNum(chart.values.high)]} barName="bar: mean plus and minus one standard deviation" dotName="mean Sharpe across splits" note={chart.note} />
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
            <p className="check-chart-row-label">{bar.label}: <span className="num">{fmtNum(bar.value, 3)}</span></p>
            <svg width={width} height={22} viewBox={`0 0 ${width} 22`} aria-hidden="true">
              <rect className={i === 0 ? 'cc-self' : 'cc-luck'} x={Math.min(px(bar.from), px(bar.to))} y={3} width={Math.max(1.5, Math.abs(px(bar.to) - px(bar.from)))} height={16} />
              <line className="cc-zero" x1={px(chart.zero)} x2={px(chart.zero)} y1={0} y2={22} />
            </svg>
          </div>
        ))}
      </div>
      <p className="muted check-chart-missing">Dashed line: zero. {chart.unitNote}.</p>
    </figure>
  )
}
