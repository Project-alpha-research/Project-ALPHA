import { describe, expect, it } from 'vitest'
import type { MarketAsset } from '../api/types'
import {
  fmtBarDate, WINDOWS, commonScale, differsMost, fmtPct, fmtRatio, fmtVolume, hoverState, linePoints, axisTicks, scaleNote, yFraction, sortAssets,
  standsOut, unitLabels,
} from './marketModel'

function asset(name: string, change: number, extra: Partial<MarketAsset> = {}): MarketAsset {
  return {
    asset: name, last_close: 10, change_1_pct: 1, change_7_pct: 2, change_window_pct: change, last_volume: 100,
    volume_vs_median: 1, median_traded_value: 1000, series: [100, 100 + change], series_ts: [1, 2],
    last_bar: '2026-11-18T00:00:00+00:00', bar_count: 120, ...extra,
  }
}

const group = [asset('AAA', 1), asset('BBB', 2), asset('CCC', 3), asset('DDD', 40), asset('EEE', -2)]

describe('differsMost', () => {
  it('picks the asset whose window change is furthest from the group median', () => {
    expect(differsMost(group)).toBe('DDD')
  })
  it('counts a large fall as different too', () => {
    expect(differsMost([...group.slice(0, 3), asset('ZZZ', -50)])).toBe('ZZZ')
  })
  it('names nothing for fewer than three assets', () => {
    expect(differsMost(group.slice(0, 2))).toBeNull()
  })
  it('breaks a tie by name', () => {
    expect(differsMost([asset('B', 5), asset('A', -5), asset('C', 0)])).toBe('A')
  })
})

describe('sortAssets', () => {
  it('sorts by a number in both directions and keeps missing values last', () => {
    const rows = [asset('A', 1, { volume_vs_median: 2 }), asset('B', 1, { volume_vs_median: null }), asset('C', 1, { volume_vs_median: 5 })]
    expect(sortAssets(rows, 'volume_vs_median', 'desc').map(row => row.asset)).toEqual(['C', 'A', 'B'])
    expect(sortAssets(rows, 'volume_vs_median', 'asc').map(row => row.asset)).toEqual(['A', 'C', 'B'])
  })
  it('sorts by name and does not change its input', () => {
    const input = [asset('B', 1), asset('A', 2)]
    expect(sortAssets(input, 'asset', 'asc').map(row => row.asset)).toEqual(['A', 'B'])
    expect(input[0].asset).toBe('B')
  })
})

describe('standsOut', () => {
  it('finds the highest volume ratio and the largest move up and down', () => {
    const rows = [asset('A', 5, { volume_vs_median: 1.2 }), asset('B', -9, { volume_vs_median: 6 }), asset('C', 12, { volume_vs_median: null })]
    const found = standsOut(rows)
    expect([found.volume?.asset, found.up?.asset, found.down?.asset]).toEqual(['B', 'C', 'B'])
  })
  it('names no mover when every move is on one side', () => {
    const found = standsOut([asset('A', 5), asset('B', 7)])
    expect(found.down).toBeNull()
    expect(found.up?.asset).toBe('B')
  })
})

describe('formatting', () => {
  it('writes signed percent, ratios and volumes with units', () => {
    expect(fmtPct(3.214)).toBe('+3.21%')
    expect(fmtPct(-0.5)).toBe('-0.50%')
    expect(fmtPct(0)).toBe('0.00%')
    expect(fmtRatio(5)).toBe('5.0×')
    expect(fmtRatio(null)).toBe('—')
    expect(fmtVolume(1234)).toBe('1.23K')
    expect(fmtVolume(2_500_000)).toBe('2.50M')
    expect(fmtVolume(12)).toBe('12')
  })
  it('names the change columns by bar size', () => {
    expect(unitLabels('day')).toEqual({ one: '1 day', seven: '7 days' })
    expect(unitLabels('bar')).toEqual({ one: '1 bar', seven: '7 bars' })
    expect(fmtBarDate('2026-11-18T00:00:00+00:00', 'day')).toBe('2026-11-18')
    expect(fmtBarDate('2026-11-18T13:00:00+00:00', 'bar')).toBe('2026-11-18 13:00 UTC')
    expect(WINDOWS).toEqual([30, 90, 365])
  })
})

describe('drawing', () => {
  it('uses one scale for all tiles and always includes the 100 start line', () => {
    expect(commonScale([asset('A', 10, { series: [100, 110] }), asset('B', -20, { series: [100, 80] })])).toEqual([80, 110])
    expect(commonScale([asset('A', 10, { series: [101, 110] })])).toEqual([100, 110])
    expect(commonScale([])).toEqual([99, 101])
  })
  it('maps a series to points inside the box, high values up', () => {
    const points = linePoints([100, 150], [100, 150], 100, 50).split(' ')
    expect(points).toEqual(['0.00,50.00', '100.00,0.00'])
  })
  it('gives a flat scale a drawable range', () => {
    expect(linePoints([5, 5], [5, 5], 10, 10)).not.toContain('NaN')
  })
  it('dims every line but the hovered one', () => {
    expect(hoverState(null, 'A')).toBe('normal')
    expect(hoverState('A', 'A')).toBe('hovered')
    expect(hoverState('A', 'B')).toBe('dimmed')
  })
  it('puts high values at the top and finds four evenly spaced gridlines', () => {
    expect(yFraction(150, [100, 150])).toBe(0)
    expect(yFraction(100, [100, 150])).toBe(1)
    const ticks = axisTicks([80, 110])
    expect(ticks.map(tick => tick.label)).toEqual(['110', '100', '90', '80'])
    expect(ticks[0].top).toBe(0)
    expect(ticks[3].top).toBe(100)
    expect(axisTicks([5, 5]).some(tick => tick.label.includes('NaN'))).toBe(false)
  })
  it('names the active scale in one line', () => {
    expect(scaleNote('shared')).toMatch(/^Scale: shared/)
    expect(scaleNote('own')).toMatch(/^Scale: each its own/)
  })
})
