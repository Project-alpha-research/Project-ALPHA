import { withAlpha } from '../util/tokens'
import { formatTime } from '../util/formatTime'
import {
  CandlestickSeries,
  type LogicalRange,
  HistogramSeries,
  createChart,
  type MouseEventParams,
  type UTCTimestamp,
} from 'lightweight-charts'
import { useEffect, useRef } from 'react'

import type { Candle, ForecastPath } from '../api/types'
import { ChartSurface } from '../theme/ChartSurface'
import { useChartPalette } from '../theme/themeState'
import { marketChartTheme } from './marketChartTheme'

interface Props {
  history: Candle[]
  sample: ForecastPath
  forecastTs: number[]
  originTs: number
}

export function KronosKlineCanvas(props: Props) {
  return <ChartSurface id="kronos.forecast"><Kline {...props}/></ChartSurface>
}

function Kline({ history, sample, forecastTs, originTs }: Props) {
  const colors = useChartPalette()
  const viewport = useRef<{ history: Candle[]; range: LogicalRange } | null>(null)
  const hostRef = useRef<HTMLDivElement>(null)
  const boundaryRef = useRef<HTMLDivElement>(null)
  const crosshairRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const host = hostRef.current
    const boundary = boundaryRef.current
    const crosshair = crosshairRef.current
    if (!host || !boundary || !crosshair) return
    const chart = createChart(host, {
      width: host.clientWidth,
      height: host.clientHeight,
      ...marketChartTheme(colors),
      timeScale: { borderColor: colors.line, timeVisible: true },
    })
    const actual = chart.addSeries(CandlestickSeries, {
      upColor: colors.up,
      downColor: colors.down,
      borderVisible: false,
      wickUpColor: colors.up,
      wickDownColor: colors.down,
      priceLineVisible: false,
    })
    actual.setData(
      history.map((bar) => ({
        time: bar.t as UTCTimestamp,
        open: bar.o,
        high: bar.h,
        low: bar.l,
        close: bar.c,
      })),
    )
    const projected = chart.addSeries(CandlestickSeries, {
      upColor: withAlpha(colors.accent, 0.72),
      downColor: withAlpha(colors.gold, 0.72),
      borderUpColor: colors.accent,
      borderDownColor: colors.gold,
      wickUpColor: colors.accent,
      wickDownColor: colors.gold,
      priceLineVisible: false,
    })
    projected.setData(
      forecastTs.map((time, index) => ({
        time: time as UTCTimestamp,
        open: sample.opens[index],
        high: sample.highs[index],
        low: sample.lows[index],
        close: sample.closes[index],
      })),
    )
    const volume = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
      lastValueVisible: false,
      priceLineVisible: false,
    })
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.84, bottom: 0 } })
    volume.setData([
      ...history.map((bar) => ({
        time: bar.t as UTCTimestamp,
        value: bar.v,
        color: bar.c >= bar.o ? withAlpha(colors.up, 0.25) : withAlpha(colors.down, 0.25),
      })),
      ...forecastTs.map((time, index) => ({
        time: time as UTCTimestamp,
        value: sample.volumes[index],
        color: withAlpha(colors.accent, 0.26),
      })),
    ])

    const positionBoundary = () => {
      const x = chart.timeScale().timeToCoordinate(originTs as UTCTimestamp)
      if (x === null) {
        boundary.hidden = true
        return
      }
      boundary.hidden = false
      boundary.style.left = `${Math.round(x)}px`
    }
    if (viewport.current?.history === history) chart.timeScale().setVisibleLogicalRange(viewport.current.range)
    else chart.timeScale().fitContent()
    positionBoundary()
    chart.timeScale().subscribeVisibleTimeRangeChange(positionBoundary)
    const handleCrosshair = (param: MouseEventParams) => {
      const actualPoint = param.seriesData.get(actual)
      const projectedPoint = param.seriesData.get(projected)
      const candle =
        actualPoint && 'open' in actualPoint
          ? actualPoint
          : projectedPoint && 'open' in projectedPoint
            ? projectedPoint
            : null
      const volumePoint = param.seriesData.get(volume)
      if (!candle || typeof param.time !== 'number') {
        crosshair.title = ''
        crosshair.textContent = 'CROSSHAIR —'
        return
      }
      const volumeValue = volumePoint && 'value' in volumePoint ? volumePoint.value : null
      crosshair.title = new Date(param.time * 1_000).toISOString()
      crosshair.textContent =
        `${formatTime(crosshair.title)}  ` +
        `O ${Number(candle.open).toFixed(4)}  H ${Number(candle.high).toFixed(4)}  ` +
        `L ${Number(candle.low).toFixed(4)}  C ${Number(candle.close).toFixed(4)}  ` +
        `V ${volumeValue === null ? '—' : Number(volumeValue).toFixed(0)}`
    }
    chart.subscribeCrosshairMove(handleCrosshair)
    const ro = new ResizeObserver(() => {
      chart.applyOptions({ width: host.clientWidth, height: host.clientHeight })
      positionBoundary()
    })
    ro.observe(host)
    return () => {
      ro.disconnect()
      chart.timeScale().unsubscribeVisibleTimeRangeChange(positionBoundary)
      chart.unsubscribeCrosshairMove(handleCrosshair)
      const range = chart.timeScale().getVisibleLogicalRange()
      viewport.current = range ? { history, range } : null
      chart.remove()
    }
  }, [colors, forecastTs, history, originTs, sample])

  return (
    <div className="kronos-kline-wrap">
      <div ref={hostRef} className="kronos-kline-host" />
      <div ref={boundaryRef} className="forecast-origin-boundary" aria-hidden="true">
        <span>FORECAST ORIGIN</span>
      </div>
      <div ref={crosshairRef} className="chart-crosshair-readout mono" aria-live="polite">
        CROSSHAIR —
      </div>
    </div>
  )
}
