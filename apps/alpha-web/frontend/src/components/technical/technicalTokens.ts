import { darkChart, type ChartPalette } from '../../theme/themes'

// The ALPHA technical chart language: dark surfaces shared with the figure canvas.
// Study identities remain stable across Classic / Default chart styles. One source for
// the Bokeh canvas and, through cssVars(), for the DOM header and legends drawn over it.

export type ChartStyleName = 'classic' | 'default'

export interface TechnicalStyle {
  name: ChartStyleName
  canvas: string
  plot: string
  /** Title band behind the chart header (Default's blue-grey band). */
  header: string
  border: string
  grid: string
  gridMonth: string
  text: string
  muted: string
  /** Header links (range buttons, Save PNG). */
  link: string
  up: string
  down: string
  volumeUp: { fill: string; edge: string }
  volumeDown: { fill: string; edge: string }
  /** Colours assigned to study series ids in order; known ids are pinned below. */
  studies: readonly string[]
  pinned: Readonly<Record<string, string>>
  rsiBand: string
  rsiOverbought: string
  rsiOversold: string
  macdLine: string
  macdSignal: string
  histFill: string
  histEdge: string
  evidenceUp: string
  evidenceDown: string
  annotation: string
  font: string
  fontSize: number
  /** Body width and OHLC tick length as fractions of one observation slot. */
  body: number
  tick: number
}

export function technicalStyle(name: ChartStyleName, colors: ChartPalette = darkChart): TechnicalStyle {
  const { bg, ink, dim, grid, up, down, link, negative, orange, purple, teal } = colors
  return {
    name, canvas: bg, plot: bg, header: bg, border: colors.border, grid, gridMonth: grid,
    text: ink, muted: dim, link, up, down,
    volumeUp: { fill: colors.volumeUp, edge: colors.volumeUpEdge },
    volumeDown: { fill: colors.volumeDown, edge: colors.volumeDownEdge },
    studies: name === 'classic' ? [link, negative, up, orange, purple, teal] : [up, link, negative, orange, purple, teal],
    pinned: { 'sma:50': link, 'sma:200': negative, 'ema:20': up, 'ema:50': link },
    rsiBand: colors.threshold, rsiOverbought: up, rsiOversold: negative,
    macdLine: ink, macdSignal: negative, histFill: name === 'classic' ? colors.classicHist : colors.defaultHist,
    histEdge: teal, evidenceUp: up, evidenceDown: down, annotation: colors.gold,
    font: 'JetBrains Mono Variable, ui-monospace, monospace', fontSize: 14, body: 0.7, tick: 0.35,
  }
}

export const CLASSIC = technicalStyle('classic')
export const DEFAULT_STYLE = technicalStyle('default')

/** Colour per study spec id: pinned ids keep their StockCharts colour, the rest cycle in order. */
export function studyColors(style: TechnicalStyle, ids: readonly string[]): Map<string, string> {
  const out = new Map<string, string>()
  const used = new Set<string>()
  for (const id of ids) if (style.pinned[id] && !out.has(id)) { out.set(id, style.pinned[id]); used.add(style.pinned[id]) }
  const free = style.studies.filter(c => !used.has(c))
  let n = 0
  for (const id of ids) if (!out.has(id)) out.set(id, free.length ? free[n++ % free.length] : style.studies[n++ % style.studies.length])
  return out
}

/** CSS custom properties so the DOM header/legends share the canvas tokens. */
export function cssVars(style: TechnicalStyle): Record<string, string> {
  return {
    '--tc-canvas': style.canvas,
    '--tc-plot': style.plot,
    '--tc-header': style.header,
    '--tc-border': style.border,
    '--tc-text': style.text,
    '--tc-muted': style.muted,
    '--tc-link': style.link,
    '--tc-up': style.up,
    '--tc-down': style.down,
    '--tc-font': `${style.fontSize}px ${style.font}`,
    '--tc-family': style.font,
  }
}
