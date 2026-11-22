import { describe, expect, it } from 'vitest'
import { EVIDENCE_LEGEND, provenanceText } from './chartHeaderModel'

describe('chart header words', () => {
  it('names the source, venue and bar size, never the internal quality tag', () => {
    const text = provenanceText({ source: 'stooq', venue: null, timeframe: '1D' })
    expect(text).toBe('stooq · venue n/a · 1D')
    expect(text).not.toContain('legacy_unqualified')
    expect(provenanceText({ source: 'stooq', venue: null, timeframe: '1D', quality_status: 'legacy_unqualified' })).toBe('stooq · venue n/a · 1D')
    expect(provenanceText({ source: 'bybit', venue: 'bybit', timeframe: '1H', quality_status: 'qualified' })).toBe('bybit · bybit · 1H · qualified')
  })
  it('has no paper trading in the legend', () => {
    expect(EVIDENCE_LEGEND).toBe('D decision · F fill')
    expect(EVIDENCE_LEGEND.toLowerCase()).not.toContain('paper')
  })
})
