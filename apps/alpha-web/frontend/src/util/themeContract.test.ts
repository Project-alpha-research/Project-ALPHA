/// <reference types="node" />
import { readFileSync, readdirSync } from 'node:fs'
import { resolve, relative } from 'node:path'
import { describe, expect, it } from 'vitest'
import { FALLBACK } from './tokens'
import { CLASSIC, DEFAULT_STYLE } from '../components/technical/technicalTokens'

const root = resolve(import.meta.dirname, '..')
const css = readFileSync(resolve(root, 'index.css'), 'utf8')
const generated = readFileSync(resolve(root, 'theme.generated.css'), 'utf8')
const dark = css.match(/\[data-theme="dark"\]\s*\{([^}]+)\}/)![1]
const tokens = Object.fromEntries([...`${dark}\n${generated}`.matchAll(/--([\w-]+):\s*(#[\da-f]{6});/gi)].map(m => [m[1], m[2]]))
const surfaces = ['bg', 'panel', 'panel-2', 'elevated', 'title']
// All seven original chrome text roles remain, with text variants for accent and negative.
const textRoles = ['ink', 'ink-dim', 'muted', 'accent-text', 'gold', 'up', 'negative-text']
function luminance(hex: string): number {
  const c = [1, 3, 5].map(i => parseInt(hex.slice(i, i + 2), 16) / 255).map(v => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)
  return c[0] * 0.2126 + c[1] * 0.7152 + c[2] * 0.0722
}
function contrast(a: string, b: string): number {
  const [first, second] = [luminance(a), luminance(b)]
  return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05)
}
function files(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap(entry => entry.isDirectory() ? files(resolve(dir, entry.name)) : [resolve(dir, entry.name)])
}
const named = 'aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue blueviolet brown burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson cyan darkblue darkcyan darkgoldenrod darkgray darkgreen darkgrey darkkhaki darkmagenta darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen darkslateblue darkslategray darkslategrey darkturquoise darkviolet deeppink deepskyblue dimgray dimgrey dodgerblue firebrick floralwhite forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green greenyellow grey honeydew hotpink indianred indigo ivory khaki lavender lavenderblush lawngreen lemonchiffon lightblue lightcoral lightcyan lightgoldenrodyellow lightgray lightgreen lightgrey lightpink lightsalmon lightseagreen lightskyblue lightslategray lightslategrey lightsteelblue lightyellow lime limegreen linen magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple mediumseagreen mediumslateblue mediumspringgreen mediumturquoise mediumvioletred midnightblue mintcream mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown seagreen seashell sienna silver skyblue slateblue slategray slategrey snow springgreen steelblue tan teal thistle tomato transparent turquoise violet wheat white whitesmoke yellow yellowgreen'.split(' ').join('|')
const namedValue = new RegExp(`(?:color|background(?:-color)?|fill|stroke|border(?:-color)?|outline|box-shadow|\\w+Color)['"]?\\s*[:=]\\s*['"\\x60]?[^;{}\\n]*?(?<![\\w.-])(?:${named})\\b(?=[;'"\\x60\\s,}])`, 'i')
const literal = /#[\da-f]{3,8}\b|\brgba?\(|\bhsla?\(/i

describe('preserved dark terminal palette', () => {
  it('has no literal colours outside explicit token definitions', () => {
    const exempt = new Set(['theme.generated.css', 'theme/themes.ts', 'api/generated.ts'])
    const failures: string[] = []
    for (const file of files(root)) {
      const name = relative(root, file)
      if (exempt.has(name) || /\.test\.|\.d\.ts$/.test(name) || !/\.(css|[tj]sx?|svg|html)$/.test(name)) continue
      let source = readFileSync(file, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '')
      if (name === 'index.css') source = source.replace(/\[data-theme="(?:light|dim|dark)"\]\s*\{[^}]+\}/g, '')
      if (literal.test(source) || namedValue.test(source)) failures.push(name)
    }
    expect(failures).toEqual([])
  })
  it('rejects named colour literals in series arrays and intermediate constants', () => {
    const quotedColour = new RegExp(`(['"\x60])(?:${named})\\1`, 'i')
    expect(quotedColour.test("const series = ['blue', 'orange']")).toBe(true)
    const failures = files(root).filter(file => {
      const name = relative(root, file)
      if (!/\.[tj]sx?$/.test(name) || /\.test\.|\.d\.ts$/.test(name) || name === 'theme/themes.ts' || name === 'api/generated.ts') return false
      return quotedColour.test(readFileSync(file, 'utf8').replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, ''))
    })
    expect(failures.map(file => relative(root, file))).toEqual([])
  })
  it.each(['color: red;', 'border: 1px solid white;', 'fill="blue"', "color: 'rebeccapurple'", "'backgroundColor': 'black'"])('rejects named colour value %s', source => {
    expect(namedValue.test(source)).toBe(true)
  })
  it.each(['color: CHART.gold,', 'color: var(--gold);', "color: 'var(--negative-text)'", 'white-space: nowrap;'])('allows token references and non-colour names %s', source => {
    expect(namedValue.test(source)).toBe(false)
  })
  it('pins the dark palette and native control scheme', () => {
    expect(tokens).toMatchObject({ bg: '#0b0b0b', panel: '#141414', 'panel-2': '#1c1c1c', line: '#2a2a2a', ink: '#e0e0e0', 'ink-dim': '#c8c8c8', muted: '#8a8a8a', accent: '#316ac5', 'accent-strong': '#4a82d8', up: '#2fc36a', down: '#e5484d', gold: '#ffd400', selection: '#1f3a66' })
    expect(css).toContain('color-scheme: dark')
  })
  it.each(textRoles.flatMap(text => surfaces.map(surface => [text, surface])))('%s text on %s clears 4.5:1', (text, surface) => {
    expect(tokens[text]).toBeDefined()
    expect(contrast(tokens[text], tokens[surface])).toBeGreaterThanOrEqual(4.5)
  })
  it.each(['selection', 'accent-soft', 'up-soft', 'down-soft', 'gold-soft'])('readable text on %s', surface => {
    const foreground = surface === 'selection' ? 'selection-ink' : ({ 'accent-soft': 'accent-text', 'up-soft': 'up', 'down-soft': 'negative-text', 'gold-soft': 'gold' } as Record<string, string>)[surface]
    expect(contrast(tokens[foreground], tokens[surface])).toBeGreaterThanOrEqual(4.5)
  })
  it.each(['line-strong', 'bevel-dark', 'accent', 'up', 'down', 'gold'])('%s control boundaries clear 3:1', role => {
    for (const surface of surfaces) expect(contrast(tokens[role], tokens[surface])).toBeGreaterThanOrEqual(3)
  })
  it.each([['accent', 'accent-text'], ['down', 'negative-text']])('%s uses the first readable white-mixed text shade', (base, text) => {
    const shades = Array.from({ length: 256 }, (_, step) => '#' + [1, 3, 5].map(i => {
      const channel = parseInt(tokens[base].slice(i, i + 2), 16)
      return Math.round(channel + (255 - channel) * step / 255).toString(16).padStart(2, '0')
    }).join(''))
    expect(tokens[text]).toBe(shades.find(shade => contrast(shade, tokens['panel-2']) >= 4.5))
  })
  it('keeps chrome focus rings visible on selected controls as well as panels', () => {
    const styles = css + readFileSync(resolve(root, 'workflow.css'), 'utf8')
    const rings = [...styles.matchAll(/[^{}]*:focus-visible[^{}]*\{([^{}]*)\}/g)]
      .flatMap(rule => [...rule[1].matchAll(/outline:\s*[^;]*var\(--([\w-]+)\)/g)].map(match => match[1]))
    expect(rings.length).toBeGreaterThan(0)
    for (const ring of rings) {
      if (ring === 'tc-link') {
        expect(contrast(CLASSIC.link, CLASSIC.canvas)).toBeGreaterThanOrEqual(3)
      } else {
        for (const surface of [...surfaces, 'selection']) expect(contrast(tokens[ring], tokens[surface])).toBeGreaterThanOrEqual(3)
      }
    }
  })
  it('keeps canvas runtime fallbacks mirrored to generated CSS', () => {
    for (const role of ['bg', 'ink', 'muted', 'grid', 'line', 'accent', 'up', 'down', 'gold'] as const) expect(FALLBACK[role]).toBe(tokens[`canvas-${role}`])
    expect(FALLBACK.dim).toBe(tokens['canvas-ink-dim'])
  })
  it.each([CLASSIC, DEFAULT_STYLE])('$name technical chart surfaces and labels are dark and readable', style => {
    expect(style.canvas).toBe(FALLBACK.bg)
    expect(style.plot).toBe(FALLBACK.bg)
    expect(style.link).toBe(tokens['accent-text'])
    for (const foreground of [style.text, style.muted, style.link, ...style.studies]) {
      for (const background of [style.canvas, style.header]) expect(contrast(foreground, background)).toBeGreaterThanOrEqual(4.5)
    }
  })
})
