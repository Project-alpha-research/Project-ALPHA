import { useId, useState } from 'react'

import './CheckCharts.css'
import { ChartNote, Legend } from './chartParts'
import { useWidth } from './useChartWidth'
import { bandLines, staircaseRows, type FoldView, type WalkForward } from './walkForwardModel'

// The walk-forward picture. Top: the price with one shaded band per tested period, a divider between folds
// and the fold's Sharpe inside the band. Below: a staircase, one thin row per fold, that fold's own warm-up
// (hatched) then its tested part (solid, same tint). Every position comes from `walkForwardModel.ts`.

const LEFT = 40
const RIGHT = 8
const BAND_TOP = 4
const LABEL_Y = 15
const ROW_H = 9
const ROW_PITCH = 12
const PRICE_NOTE = 'line: price from the bars stored now; the run’s own bars were not saved with it'

interface Frame {
  px: (x: number) => number
  py: (y: number) => number
  bandBottom: number
}

function PriceLayer({ chart, frame, patternId }: { chart: WalkForward; frame: Frame; patternId: string }) {
  const { px, py, bandBottom } = frame
  const line = chart.price.map((p) => `${px(p.x).toFixed(1)},${py(p.y).toFixed(1)}`).join(' ')
  const beforePx = px(chart.firstTestX) - px(0)
  return (
    <g>
      <defs>
        <pattern id={patternId} width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="5" className="cc-warm" />
        </pattern>
      </defs>
      {chart.folds.map((f) => {
        const width = Math.max(1, px(f.testX1) - px(f.testX0))
        return (
          <g key={f.fold} className="cc-fold" tabIndex={0} role="img" aria-label={f.title}>
            <title>{f.title}</title>
            <rect className={`cc-tint-${f.tint}`} x={px(f.testX0)} y={BAND_TOP} width={width} height={bandBottom - BAND_TOP} />
            {(bandLines(f, width) ?? []).map((line, i) => (
              <text key={line} className="cc-halo" x={px(f.testX0) + width / 2} y={LABEL_Y + i * 11} textAnchor="middle" fontSize="10">{line}</text>
            ))}
          </g>
        )
      })}
      {[...chart.folds.map((f) => f.testX0), chart.folds[chart.folds.length - 1].testX1].map((x, i) => (
        <line key={i} className="cc-divider" x1={px(x)} x2={px(x)} y1={BAND_TOP} y2={bandBottom} />
      ))}
      {line ? <polyline className="cc-price" points={line} /> : null}
      {chart.priceTicks.map((t) => (
        <text key={t.y} x={LEFT - 4} y={py(t.y) + 3} textAnchor="end" className="cc-dim">{t.label}</text>
      ))}
      {beforePx >= 118 ? <text x={LEFT + 4} y={LABEL_Y} className="cc-dim cc-halo" fontSize="10">before the first test</text> : null}
      {chart.overlaps.map((o) => (
        <rect key={o.fold} className="cc-overlap" x={px(o.x0)} y={BAND_TOP} width={Math.max(2, px(o.x1) - px(o.x0))} height={bandBottom - BAND_TOP} />
      ))}
    </g>
  )
}

function Row({ f, y, frame, patternId }: { f: FoldView; y: number; frame: Frame; patternId: string }) {
  const { px } = frame
  return (
    <g>
      <text x={LEFT - 6} y={y + ROW_H - 1} textAnchor="end" className="cc-dim" fontSize="8.5">{f.fold}</text>
      <rect className="cc-stair-warm" x={px(f.trainX0)} y={y} width={Math.max(1, px(f.trainX1) - px(f.trainX0))} height={ROW_H} fill={`url(#${patternId})`} />
      <rect className={`cc-stair-test cc-tint-${f.tint}`} x={px(f.testX0)} y={y} width={Math.max(1, px(f.testX1) - px(f.testX0))} height={ROW_H} />
      {f.overlap ? <rect className="cc-overlap-row" x={px(f.overlap.x0)} y={y} width={Math.max(2, px(f.overlap.x1) - px(f.overlap.x0))} height={ROW_H} /> : null}
    </g>
  )
}

function Axis({ chart, frame, y, width }: { chart: WalkForward; frame: Frame; y: number; width: number }) {
  const { px } = frame
  const first = new Date(chart.t0).toISOString().slice(0, 10)
  const last = new Date(chart.t1).toISOString().slice(0, 10)
  const room = (x: number): boolean => px(x) - LEFT > 80 && width - RIGHT - px(x) > 80
  return (
    <g>
      <line className="cc-axis" x1={LEFT} x2={width - RIGHT} y1={y} y2={y} />
      {chart.yearTicks.filter((t) => room(t.x)).map((t) => (
        <g key={t.label}>
          <line className="cc-axis" x1={px(t.x)} x2={px(t.x)} y1={y} y2={y + 4} />
          <text x={px(t.x)} y={y + 14} textAnchor="middle" className="cc-dim">{t.label}</text>
        </g>
      ))}
      <text x={LEFT} y={y + 14}>{first}</text>
      <text x={width - RIGHT} y={y + 14} textAnchor="end">{last}</text>
    </g>
  )
}

export function WalkForwardView({ chart, initialExpanded = false }: { chart: WalkForward; initialExpanded?: boolean }) {
  const [ref, measured] = useWidth()
  const [expanded, setExpanded] = useState(initialExpanded)
  const patternId = `cc-hatch-${useId().replaceAll(':', '')}`
  const width = measured
  const hasPrice = chart.price.length > 0
  const priceTop = 34
  const priceBottom = hasPrice ? 104 : 36
  const bandBottom = priceBottom + 4
  const plot = width - LEFT - RIGHT
  const frame: Frame = { px: (x) => LEFT + x * plot, py: (y) => priceBottom - y * (priceBottom - priceTop), bandBottom }
  const rows = staircaseRows(chart.folds, expanded)
  const axisY = bandBottom + 4
  const stairTop = axisY + 24
  const gapH = rows.hidden > 0 ? 16 : 0
  const bottomTop = stairTop + rows.top.length * ROW_PITCH + gapH
  const height = bottomTop + rows.bottom.length * ROW_PITCH + 4
  return (
    <figure className="check-chart">
      {chart.intro ? <p className="check-chart-intro">{chart.intro}</p> : null}
      {chart.priceNote ? <ChartNote text={`${chart.priceNote[0].toUpperCase()}${chart.priceNote.slice(1)}.`} /> : null}
      <div ref={ref}>
        <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="group" aria-label={chart.summary}>
          <PriceLayer chart={chart} frame={frame} patternId={patternId} />
          <Axis chart={chart} frame={frame} y={axisY} width={width} />
          <g aria-hidden="true">
            {rows.top.map((f, i) => <Row key={f.fold} f={f} y={stairTop + i * ROW_PITCH} frame={frame} patternId={patternId} />)}
            {rows.hidden > 0 ? <text x={LEFT} y={stairTop + rows.top.length * ROW_PITCH + 11} className="cc-dim">{`… ${rows.total} folds in total`}</text> : null}
            {rows.bottom.map((f, i) => <Row key={f.fold} f={f} y={bottomTop + i * ROW_PITCH} frame={frame} patternId={patternId} />)}
          </g>
        </svg>
      </div>
      {chart.collapsible ? (
        <button type="button" className="check-chart-toggle" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
          {expanded ? 'show fewer folds' : 'show all folds'}
        </button>
      ) : null}
      <Legend items={[
        ...(hasPrice ? [{ text: PRICE_NOTE }] : []),
        { cls: 'warm', text: chart.trainLabel },
        { cls: 'test', text: 'tested here, not seen before (number: out-of-sample Sharpe)' },
        { text: 'unshaded price: before the first test' },
        ...(chart.warning ? [{ cls: 'warn', text: chart.warning }] : []),
      ]} />
      {chart.warning ? <p className="check-chart-warning">Warning: {chart.warning}. The yellow marks show the shared dates.</p> : null}
    </figure>
  )
}
