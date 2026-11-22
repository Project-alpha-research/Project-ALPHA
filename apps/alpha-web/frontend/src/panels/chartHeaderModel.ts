// Words in the price chart's header and legend. The stored quality tag is internal and is not shown.

export const EVIDENCE_LEGEND = 'D decision · F fill'

export function provenanceText(p: { source: string; venue?: string | null; timeframe: string }): string {
  return `${p.source} · ${p.venue ?? 'venue n/a'} · ${p.timeframe}`
}
