import { describe, expect, it } from 'vitest'
import { EVIDENCE_LEGEND, provenanceText } from './chartHeaderModel'

describe('chart header words', () => {
  it('names the source, venue and bar size, never the internal quality tag', () => {
    const text = provenanceText({ source: 'stooq', venue: null, timeframe: '1D' })
    expect(text).toBe('stooq · venue n/a · 1D')
    expect(text).not.toContain('legacy_unqualified')
  })
  it('has no paper trading in the legend', () => {
    expect(EVIDENCE_LEGEND).toBe('D decision · F fill')
    expect(EVIDENCE_LEGEND.toLowerCase()).not.toContain('paper')
  })
})
