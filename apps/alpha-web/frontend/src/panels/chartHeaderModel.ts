// Words in the price chart's header and legend. The stored quality tag is internal and is not shown.

export const EVIDENCE_LEGEND = 'D decision · F fill'

/** The stored quality tag of a bar set that was never qualified is an internal word; it is not shown. */
export const INTERNAL_QUALITY_TAG = 'legacy_unqualified'

export function provenanceText(p: { source: string; venue?: string | null; timeframe: string; quality_status?: string }): string {
  const base = `${p.source} · ${p.venue ?? 'venue n/a'} · ${p.timeframe}`
  return p.quality_status && p.quality_status !== INTERNAL_QUALITY_TAG ? `${base} · ${p.quality_status}` : base
}
