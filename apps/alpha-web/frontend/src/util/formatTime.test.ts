import { describe, expect, it } from 'vitest'
import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { Timestamp, formatDuration, formatTime } from './formatTime'

describe('UTC display times', () => {
  it.each([
    ['2026-11-17T14:33:56Z', '17 Nov 2026, 14:33 UTC'],
    ['2026-11-01T00:00:00Z', '1 Nov 2026, 00:00 UTC'],
    ['2026-11-01', '1 Nov 2026, 00:00 UTC'],
    ['2026-11-17T00:33:00+10:00', '16 Nov 2026, 14:33 UTC'],
  ])('formats %s without local-time conversion', (iso, expected) => {
    expect(formatTime(iso)).toBe(expected)
  })
  it.each(['bad', '', '2026-11-17T14:33:00', '2026-02-30T00:00:00Z'])('rejects invalid or timezone-free time %s', value => {
    expect(() => formatTime(value)).toThrow(/invalid/i)
  })
  it.each([[0, '<1 min'], [0.5, '<1 min'], [24, '24 min'], [81, '1 h 21 min'], [60, '1 h'], [1501, '25 h 1 min']])('formats %s recorded minutes', (minutes, expected) => {
    expect(formatDuration(minutes)).toBe(expected)
  })
  it('retains exact timestamps in hover titles, including epoch values and missing times', () => {
    expect(renderToStaticMarkup(createElement(Timestamp, { value: '2026-11-17T14:33:56Z' }))).toContain('title="2026-11-17T14:33:56Z"')
    expect(renderToStaticMarkup(createElement(Timestamp, { value: 0 }))).toContain('1 Jan 1970, 00:00 UTC')
    expect(renderToStaticMarkup(createElement(Timestamp, { value: null }))).toBe('—')
  })
  it('shows an unparseable value as received instead of breaking the panel', () => {
    const html = renderToStaticMarkup(createElement(Timestamp, { value: '2026-11-17 14:33' }))
    expect(html).toContain('2026-11-17 14:33')
    expect(html).toContain('title="2026-11-17 14:33"')
  })
  it.each([-1, NaN, Infinity])('rejects invalid duration %s', value => {
    expect(() => formatDuration(value)).toThrow(/invalid/i)
  })
})
