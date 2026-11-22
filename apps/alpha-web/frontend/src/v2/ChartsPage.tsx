// Charts: the stored daily bars of one symbol, full height, with volume, SMA 50/200, an RSI pane and
// the pattern overlays `alpha chart overlays` computes. Bars from the reserved start on are shaded.

import { useEffect, useMemo, useState } from 'react'
import { createChartLinkRegistry } from '../shell/chartLinkRegistry'
import type { ChartOverlays } from '../api/types'
import { useChartPalette } from '../theme/themeState'
import { withAlpha } from '../util/tokens'
import { api } from '../api/client'
import type { Candle } from '../api/types'
import { PriceChartCanvas } from '../components/PriceChartCanvas'
import { useChartHover } from '../context/chartHover'
import { overlayQuery, PATTERN_LABEL, PATTERNS, type PatternName } from '../panels/chartOverlaysModel'
import { DeskChartSurface } from './DeskChartSurface'
import { formatNumber } from './deskModel'
import { HELD_BACK_LABEL, heldBackPrimitive } from './heldBackPrimitive'
import { Empty, Problem, Skeleton } from './parts'
import { useLoad } from './useLoad'

const STUDIES = [
  { spec: 'sma:50', label: 'SMA 50' },
  { spec: 'sma:200', label: 'SMA 200' },
  { spec: 'rsi:14', label: 'RSI 14' },
] as const
const WINDOWS = [
  { id: '6M', days: 183 }, { id: '1Y', days: 365 }, { id: '3Y', days: 1096 }, { id: '5Y', days: 1826 }, { id: 'All', days: null },
] as const
type WindowId = (typeof WINDOWS)[number]['id']
const PATTERN_SHORT: Partial<Record<PatternName, string>> = { swings: 'Pivots', trendlines: 'Trend lines', levels: 'Fibonacci', market_profile: 'Profile levels' }

function day(seconds: number): string {
  return new Date(seconds * 1000).toISOString().slice(0, 10)
}

function Readout({ bars }: { bars: readonly Candle[] }) {
  const hover = useChartHover().bar
  const bar = hover ?? bars[bars.length - 1]
  if (!bar) return null
  const previous = bars[bars.findIndex(item => item.t === bar.t) - 1]
  const change = previous ? (bar.c / previous.c - 1) * 100 : null
  const tone = change === null || change === 0 ? '' : change > 0 ? 'up' : 'down'
  return <div className="d-ohlc mono" aria-live="off">
    <span>{day(bar.t)}</span>
    <span>O <b>{formatNumber(bar.o)}</b></span><span>H <b>{formatNumber(bar.h)}</b></span>
    <span>L <b>{formatNumber(bar.l)}</b></span><span>C <b className={tone}>{formatNumber(bar.c)}</b></span>
    {change !== null ? <span className={tone}>{change > 0 ? '▲' : change < 0 ? '▼' : ''} {Math.abs(change).toFixed(2)}%</span> : null}
    <span>V <b>{bar.v.toLocaleString('en-US')}</b></span>
  </div>
}

/**
 * The price chart with the held-back period shaded in the chart palette's warning colour. The
 * window buttons only move the visible range over the bars already loaded; nothing is refetched.
 */
function ShadedChart({ bars, overlays, firstHeld, span }: { bars: Candle[]; overlays: ChartOverlays | null; firstHeld: number | null; span: WindowId }) {
  const colors = useChartPalette()
  const primitive = useMemo(() => firstHeld === null ? null : heldBackPrimitive(firstHeld, withAlpha(colors.gold, 0.08), withAlpha(colors.gold, 0.9)), [firstHeld, colors])
  const registry = useMemo(() => { const value = createChartLinkRegistry(); value.configure(true, false); return value }, [])
  useEffect(() => registry.register('desk-window', { range: () => undefined, cursor: () => undefined }), [registry])
  useEffect(() => {
    const last = bars[bars.length - 1]?.t
    if (last === undefined) return
    const days = WINDOWS.find(item => item.id === span)?.days ?? null
    const timer = globalThis.setTimeout(() => registry.publish('desk-window', 'range', days === null ? bars[0].t : last - days * 86_400, last), 60)
    return () => globalThis.clearTimeout(timer)
  }, [registry, bars, span])
  return <PriceChartCanvas bars={bars} overlays={overlays} primitive={primitive} registry={registry} panelId="desk-chart" />
}

function Toggle({ on, label, onClick, title }: { on: boolean; label: string; onClick(): void; title?: string }) {
  return <button type="button" className="d-toggle" aria-pressed={on} onClick={onClick} title={title}>{label}</button>
}

export function ChartsPage({ symbol, reservedStart }: { symbol: string; reservedStart: string | null }) {
  const [studies, setStudies] = useState<string[]>(['sma:50', 'sma:200'])
  const [patterns, setPatterns] = useState<PatternName[]>(['swings'])
  const [span, setSpan] = useState<WindowId>('1Y')
  const bars = useLoad(() => api.candles(symbol), `bars:${symbol}`, `the bars for ${symbol}`)
  const query = overlayQuery({ indicators: studies, patterns }, { end: null, snapshotId: null })
  const overlays = useLoad(() => query ? api.overlays(symbol, query) : Promise.resolve(null), `overlays:${symbol}${query}`, 'the overlays')
  const candles = bars.state === 'ready' ? bars.value.bars : null
  const reservedTs = reservedStart ? Date.parse(`${reservedStart}T00:00:00Z`) / 1000 : null
  const firstHeld = candles && reservedTs !== null ? candles.find(bar => bar.t >= reservedTs)?.t ?? null : null
  const flip = <T,>(list: T[], item: T) => list.includes(item) ? list.filter(value => value !== item) : [...list, item]
  const last = candles?.[candles.length - 1]
  return <div className="d-charts">
    <div className="d-chart-bar">
      <strong className="d-chart-symbol mono">{symbol}</strong>
      <span className="d-chip">Daily</span>
      {candles ? <Readout bars={candles} /> : <span className="d-muted">—</span>}
      <span className="d-grow" />
      <div className="d-toggles" role="group" aria-label="Visible range">
        {WINDOWS.map(item => <Toggle key={item.id} on={span === item.id} label={item.id} onClick={() => setSpan(item.id)} title={item.days ? `Show the last ${item.id}` : 'Show every stored bar'} />)}
      </div>
      <div className="d-toggles" role="group" aria-label="Studies">
        {STUDIES.map(study => <Toggle key={study.spec} on={studies.includes(study.spec)} label={study.label} onClick={() => setStudies(flip(studies, study.spec))} />)}
      </div>
      <details className="d-menu">
        <summary className="d-btn">Patterns{patterns.length ? ` · ${patterns.length}` : ''}</summary>
        <div className="d-menu-body" role="group" aria-label="Pattern overlays">
          {PATTERNS.map(name => <label key={name} className="d-check"><input type="checkbox" checked={patterns.includes(name)} onChange={() => setPatterns(flip(patterns, name))} />
            <span><strong>{PATTERN_SHORT[name] ?? PATTERN_LABEL[name].split(' (')[0]}</strong><small>{PATTERN_LABEL[name]}</small></span></label>)}
        </div>
      </details>
    </div>
    <div className="d-chart-stage">
      {bars.state === 'loading' ? <div className="d-chart-wait"><Skeleton rows={1} height={420} label={`Loading the bars for ${symbol}`} /></div>
        : bars.state === 'error' ? <Problem>{bars.text}</Problem>
        : !candles?.length ? <Empty>No daily bars are stored for {symbol}. Choose another symbol in the box at the top.</Empty>
        : <DeskChartSurface className="d-chart-canvas">
          <ShadedChart bars={candles} overlays={overlays.state === 'ready' ? overlays.value : null} firstHeld={firstHeld} span={span} />
        </DeskChartSurface>}
    </div>
    <footer className="d-chart-foot">
      <span>{candles ? `${candles.length.toLocaleString('en-US')} daily bars · ${day(candles[0].t)} to ${last ? day(last.t) : '—'}` : ''}</span>
      {reservedStart ? <span className="d-held-key"><i aria-hidden="true" />{HELD_BACK_LABEL} (from {reservedStart}){firstHeld === null && candles ? ': no stored bar is in that period.' : ''}</span> : null}
      {overlays.state === 'loading' && query ? <span className="d-muted">Computing overlays…</span>
        : overlays.state === 'error' ? <span className="d-down" role="alert">{overlays.text}</span>
        : <span className="d-muted">Studies and patterns are computed by the engine from the stored bars.</span>}
    </footer>
  </div>
}
