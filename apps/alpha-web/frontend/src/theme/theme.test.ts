/// <reference types="node" />
import { readFileSync } from 'node:fs'
import { runInNewContext } from 'node:vm'
import { describe, expect, it, vi } from 'vitest'
import { darkChart, lightChart, type ChartPalette } from './themes'
import { technicalStyle } from '../components/technical/technicalTokens'
import { readTokens } from '../util/tokens'

const html = readFileSync(new URL('../../index.html', import.meta.url), 'utf8')
const css = readFileSync(new URL('../index.css', import.meta.url), 'utf8')

describe('workstation themes', () => {
  it.each([[null, 'light'], ['unknown', 'light'], ['dim', 'dim'], ['dark', 'dark']])(
    'applies the stored choice %s in the document head before paint', (saved, expected) => {
      const head = html.split('</head>')[0]
      const script = head.match(/<script>([\s\S]*?)<\/script>/)?.[1]
      expect(script).toBeDefined()
      const documentElement = { dataset: { theme: '' } }
      runInNewContext(script!, { document: { documentElement }, localStorage: { getItem: (key: string) => key === 'alpha.theme.v1' ? saved : null } })
      expect(documentElement.dataset.theme).toBe(expected)
    },
  )

  for (const theme of ['light', 'dim', 'dark']) {
    it(`checks every chrome text role and surface in ${theme}`, () => {
      const block = css.match(new RegExp(`\\[data-theme="${theme}"\\]\\s*\\{([^}]+)`))?.[1]
      expect(block).toBeDefined()
      const tokens = Object.fromEntries([...block!.matchAll(/--([\w-]+):\s*(#[a-f\d]{6});/gi)].map(m => [m[1], m[2]]))
      const backgrounds = ['bg', 'panel', 'panel-2', 'elevated', 'title', 'field-bg', 'accent-soft', 'up-soft', 'down-soft', 'gold-soft']
      for (const role of ['ink', 'ink-dim', 'muted', 'accent-text', 'negative-text', 'up', 'gold']) {
        for (const bg of backgrounds) expect(contrast(tokens[role], tokens[bg]), role + ' on ' + bg).toBeGreaterThanOrEqual(role === 'ink' ? 7 : 4.5)
      }
      expect(contrast(tokens['selection-ink'], tokens.selection)).toBeGreaterThanOrEqual(4.5)
      for (const bg of [...backgrounds, 'selection']) expect(contrast(tokens['line-strong'], tokens[bg])).toBeGreaterThanOrEqual(3)
    })
  }
})

function contrast(a: string, b: string) {
  function luminance(hex: string) {
    const [r, g, blue] = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255)
      .map(c => c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4)
    return 0.2126 * r + 0.7152 * g + 0.0722 * blue
  }
  const x = luminance(a), y = luminance(b)
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05)
}

describe('browser chart surfaces', () => {
  it.each([['Light', lightChart], ['Dim', lightChart], ['Dark', darkChart]] as const)(
    '%s labels, studies and values are readable against the chart surface', (_, palette) => {
      expect(contrast(palette.ink, palette.bg)).toBeGreaterThanOrEqual(7)
      for (const styleName of ['classic', 'default'] as const) {
        const style = technicalStyle(styleName, palette)
        for (const color of [style.text, style.link, style.muted, style.down, style.annotation, style.histEdge, ...style.studies]) {
          expect(contrast(color, style.canvas)).toBeGreaterThanOrEqual(4.5)
        }
      }
    },
  )

  it('reads the palette of each host again when its theme changes', () => {
    const light = {} as Element, dark = {} as Element
    const palettes = new Map([[light, lightChart], [dark, darkChart]])
    vi.stubGlobal('getComputedStyle', (node: Element) => ({
      getPropertyValue: (key: string) => palettes.get(node)![key.slice('--chart-'.length) as keyof ChartPalette],
    }))
    try {
      expect(readTokens(light)).toEqual(lightChart)
      expect(readTokens(dark)).toEqual(darkChart)
      palettes.set(dark, lightChart)
      expect(readTokens(dark)).toEqual(lightChart)
    } finally {
      vi.unstubAllGlobals()
    }
  })
})
