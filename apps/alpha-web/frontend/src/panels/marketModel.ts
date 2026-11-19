// Market overview model: pure helpers for the Market screen. The server sends every number;
// this file only orders, formats and positions them. It computes no metric and no verdict.

import type { MarketAsset } from '../api/types'

export const WINDOWS = [30, 90, 365] as const
export type SortKey =
  | 'asset' | 'last_close' | 'change_1_pct' | 'change_7_pct' | 'change_window_pct' | 'last_volume' | 'volume_vs_median'
export type SortDirection = 'asc' | 'desc'

export function median(values: readonly number[]): number {
  const sorted = [...values].sort((a, b) => a - b)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[middle] : (sorted[middle - 1] + sorted[middle]) / 2
}

/** The asset whose window change is furthest from the group median (either way); no verdict. */
export function differsMost(assets: readonly MarketAsset[]): string | null {
  if (assets.length < 3) return null
  const centre = median(assets.map(item => item.change_window_pct))
  let best: MarketAsset | null = null
  let bestGap = -1
  for (const item of assets) {
    const gap = Math.abs(item.change_window_pct - centre)
    if (gap > bestGap || (gap === bestGap && best !== null && item.asset < best.asset)) {
      best = item
      bestGap = gap
    }
  }
  return best?.asset ?? null
}

export function sortAssets(assets: readonly MarketAsset[], key: SortKey, direction: SortDirection): MarketAsset[] {
  const sign = direction === 'asc' ? 1 : -1
  return [...assets].sort((a, b) => {
    const left = a[key]
    const right = b[key]
    if (left === null && right === null) return a.asset.localeCompare(b.asset)
    if (left === null) return 1
    if (right === null) return -1
    if (typeof left === 'string' || typeof right === 'string') return sign * String(left).localeCompare(String(right))
    return left === right ? a.asset.localeCompare(b.asset) : sign * (left - right)
  })
}

export interface StandsOut { volume: MarketAsset | null; up: MarketAsset | null; down: MarketAsset | null }

export function standsOut(assets: readonly MarketAsset[]): StandsOut {
  let volume: MarketAsset | null = null
  let up: MarketAsset | null = null
  let down: MarketAsset | null = null
  for (const item of assets) {
    if (item.volume_vs_median !== null && (volume === null || item.volume_vs_median > (volume.volume_vs_median ?? 0))) volume = item
    if (item.change_window_pct > 0 && (up === null || item.change_window_pct > up.change_window_pct)) up = item
    if (item.change_window_pct < 0 && (down === null || item.change_window_pct < down.change_window_pct)) down = item
  }
  return { volume, up, down }
}

export function fmtPct(value: number): string {
  const text = Math.abs(value).toFixed(2)
  if (Number(text) === 0) return '0.00%'
  return `${value < 0 ? '-' : '+'}${text}%`
}

export function fmtRatio(value: number | null): string {
  return value === null ? '—' : `${value.toFixed(1)}×`
}

export function fmtVolume(value: number): string {
  if (value >= 1e9) return `${(value / 1e9).toFixed(2)}B`
  if (value >= 1e6) return `${(value / 1e6).toFixed(2)}M`
  if (value >= 1e3) return `${(value / 1e3).toFixed(2)}K`
  return String(Number(value.toFixed(2)))
}

export function fmtPrice(value: number): string {
  return Number(value.toPrecision(7)).toLocaleString('en-US', { maximumFractionDigits: 8 })
}

export function unitLabels(unit: 'day' | 'bar'): { one: string; seven: string } {
  return unit === 'day' ? { one: '1 day', seven: '7 days' } : { one: '1 bar', seven: '7 bars' }
}

/** One y range for every tile so an outlier is visible; the 100 start line is always inside. */
export function commonScale(assets: readonly MarketAsset[]): [number, number] {
  const all = assets.flatMap(item => item.series)
  if (!all.length) return [99, 101]
  return [Math.min(100, ...all), Math.max(100, ...all)]
}

/** The drawn range: a flat range is widened so nothing divides by zero. */
function drawRange(scale: readonly [number, number]): [number, number] {
  return scale[1] === scale[0] ? [scale[0] - 0.5, scale[1] + 0.5] : [scale[0], scale[1]]
}

/** Where a value sits in the box, 0 at the top and 1 at the bottom. */
export function yFraction(value: number, scale: readonly [number, number]): number {
  const [low, high] = drawRange(scale)
  return 1 - (value - low) / (high - low)
}

export function linePoints(series: readonly number[], scale: readonly [number, number], width: number, height: number): string {
  const last = Math.max(series.length - 1, 1)
  return series
    .map((value, index) => `${((index / last) * width).toFixed(2)},${(yFraction(value, scale) * height).toFixed(2)}`)
    .join(' ')
}

export interface AxisTick { value: number; label: string; top: number }

/** Four labelled gridlines, evenly spaced over the drawn range. `top` is a percentage from the top edge. */
export function axisTicks(scale: readonly [number, number]): AxisTick[] {
  const [low, high] = drawRange(scale)
  const digits = high - low < 10 ? 1 : 0
  return [0, 1, 2, 3].map(step => {
    const value = high - ((high - low) * step) / 3
    return { value, label: value.toFixed(digits), top: yFraction(value, scale) * 100 }
  })
}

export type ScaleMode = 'shared' | 'own'

export function scaleNote(mode: ScaleMode): string {
  return mode === 'shared'
    ? 'Scale: shared. Every tile uses one range, so an outlier stands out. 100 is the first bar of the window.'
    : 'Scale: each its own. Every tile fills its own range, so compare shapes, not sizes. 100 is the first bar of the window.'
}

export type HoverState = 'normal' | 'hovered' | 'dimmed'

export function hoverState(hovered: string | null, asset: string): HoverState {
  if (hovered === null) return 'normal'
  return hovered === asset ? 'hovered' : 'dimmed'
}

/** A stored bar's UTC date; intraday stores also show the time. */
export function fmtBarDate(iso: string, unit: 'day' | 'bar'): string {
  return unit === 'day' ? iso.slice(0, 10) : `${iso.slice(0, 10)} ${iso.slice(11, 16)} UTC`
}
