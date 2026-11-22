import { describe, expect, it } from 'vitest'

import { barsText, hoveredText, statusSegments, utcClock } from './statusBarModel'

const NOON = Date.UTC(2026, 8, 3, 12, 34, 56)

describe('statusBarModel', () => {
  it('lays the segments out in order', () => {
    const segments = statusSegments({ profile: 'equities', now: NOON, hovered: null, barsLoaded: 2738 })
    expect(segments.map((item) => item.id)).toEqual(['help', 'profile', 'clock', 'ohlc', 'bars'])
    expect(segments[0].text).toBe('For Help, press F1')
    expect(segments[1].text).toBe('Market: Stocks & ETFs')
    expect(segments[2].text).toBe('3 Sep 2026, 12:34 UTC')
    expect(segments[3].text).toBe('O: — H: — L: — C: — V: —')
    expect(segments[4].text).toBe('2,738 / 2,738 bars')
  })

  it('renders an injected clock and refuses an invalid one', () => {
    expect(utcClock(NOON)).toBe('3 Sep 2026, 12:34 UTC')
    expect(() => utcClock(Number.NaN)).toThrow(/invalid time/)
  })

  it('prints — for no hovered bar and throws on a non-finite price', () => {
    expect(hoveredText(null)).toBe('O: — H: — L: — C: — V: —')
    expect(hoveredText({ t: 0, o: 100, h: 101.5, l: 99.25, c: 100.75, v: 31204 })).toBe(
      'O: 100 H: 101.5 L: 99.25 C: 100.75 V: 31,204',
    )
    expect(() => hoveredText({ t: 0, o: Number.NaN, h: 1, l: 1, c: 1, v: 1 })).toThrow(/non-finite/)
    expect(barsText(0)).toBe('0 / 0 bars')
  })
})
