import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { RunListItem } from '../api/types'
import { GLOSSARY } from '../explain/glossary'
import { gateStories } from '../explain/gates'
import type { ValidateManifest } from '../explain/types'
import validateA from '../explain/__fixtures__/validate-a.json'
import validateB from '../explain/__fixtures__/validate-b.json'
import validateD from '../explain/__fixtures__/validate-d-kronos.json'
import { edgeReviewRows } from './edgeReviewModel'
import { paletteHint, toastDetail } from './readingModel'
import { summaryRows } from './reportModel'
import { Gates } from './rundetail/Gates'
import { ExplainCard } from './rundetail/common'
import { SOME } from './__fixtures__/readings'
import { BANNED } from './__fixtures__/scanWords'

// Owner-facing words that left these screens, and a lone letter grade. The owner's phrase for the old level ("the level used by
// the old grade"), the retired-grade glossary name and the muted old-rules line are taken out before the scan.
const ALLOWED = /the level used by the old grade|old grade|graded [A-Z]+ under the old rules/gi
const LETTER = /(?<![\w'./-])[A-F](?![\w'./-])/
const ARTICLE = /(?:^|(?<=[.!?:] ))A(?= [A-Za-z])/gm

function words(html: string): string {
  return html.replace(/<style[\s\S]*?<\/style>/g, '').replace(/<[^>]+>/g, '\n').replaceAll('&amp;', '&').replaceAll('&#x27;', "'")
}
function assertOwnerText(html: string): void {
  const text = words(html).replace(ALLOWED, '')
  expect(text.match(BANNED)?.[0]).toBeUndefined()
  expect(ARTICLE[Symbol.replace](text, '').match(LETTER)?.[0]).toBeUndefined()
}

const base = { run_id: 'abcd00000000beef', kind: 'runs', command: 'validate', label: 'synthetic', mtime: 1_700_000_000 } as unknown as RunListItem
const runs: [string, RunListItem][] = [
  ['an old run with a letter and a gate flag', { ...base, evidence: null, verdict: 'C', passed: false } as RunListItem],
  ['an old run that passed its gates', { ...base, evidence: null, verdict: 'A', passed: true } as RunListItem],
  ['a new run with an evidence word', { ...base, evidence: 'some evidence', verdict: 'B', passed: false } as RunListItem],
  ['a fault', { ...base, evidence: 'fault', verdict: 'F', passed: false } as RunListItem],
]

describe('the Summary table', () => {
  it.each([[validateA], [validateB], [validateD]])('has no Passed row and no grade word, old style and new style', manifest => {
    for (const shaped of [manifest, { ...manifest, reading: SOME }]) {
      const rows = summaryRows(shaped as Record<string, unknown>)
      expect(rows.map(row => row.label)).not.toContain('Passed')
      assertOwnerText(rows.map(row => `<td>${row.label}</td><td>${row.value}</td>`).join(''))
    }
  })
})

const family = (name: string, grade: string) => ({
  family: name, status: 'warning', risk_grade: grade, n_paths: 5000, terminal_return_q05: -0.121, terminal_return_q50: 0.042, terminal_return_q95: 0.2,
  maximum_drawdown_q50: 0.091, maximum_drawdown_q95: 0.21, loss_probability: { point: 0.31, lower: 0.298, upper: 0.322 },
})

describe('the Monte Carlo risk readings', () => {
  it.each([['D'], ['A']])('shows the stored percentiles in plain words and never the risk grade %s', grade => {
    const manifest = { command: 'monte_carlo_classical', status: 'warning', families: [family('iid_empirical', grade), family('student_t', grade)] }
    const rows = summaryRows(manifest)
    const mc = rows.filter(row => row.label.startsWith('Monte Carlo'))
    expect(mc.map(row => row.label)).toEqual(['Monte Carlo · iid_empirical', 'Monte Carlo · student_t'])
    expect(mc[0].value).toBe('5,000 paths · median final return 4.2% · 5th percentile -12.1% · 95th percentile 20.0% · median largest fall 9.1% · '
      + 'largest fall at the 95th percentile 21.0% · share of paths ending below zero 31.0% (95% range 29.8% to 32.2%)')
    assertOwnerText(rows.map(row => `<td>${row.label}</td><td>${row.value}</td>`).join(''))
  })
  it('shows not recorded for a family with no stored numbers, never a made-up one', () => {
    expect(summaryRows({ families: [{ family: 'student_t' }] }).find(row => row.label === 'Monte Carlo · student_t')?.value).toBe('not recorded')
  })
})

describe('the Gates tab', () => {
  it.each([['validate-a', validateA], ['validate-b', validateB], ['validate-d', validateD]])('reads %s as numbers and fact checks', (_name, manifest) => {
    for (const shaped of [manifest, { ...manifest, reading: SOME }]) {
      assertOwnerText(renderToStaticMarkup(<Gates manifest={shaped as unknown as ValidateManifest} runId="abcd00000000beef" />))
    }
  })
  it('keeps one fact check as a state word and shows the old level muted on the statistical ones', () => {
    const html = renderToStaticMarkup(<Gates manifest={validateB as unknown as ValidateManifest} runId="abcd00000000beef" />)
    expect(html).toContain('>computed<')
    expect(html).not.toContain('>sound<')
    expect(html).toContain('computed means the check could run; it does not say the result is good')
    expect(html).toMatch(/the level used by the old grade/i)
    expect(html).not.toContain('class="chip pass"')
    expect(html).not.toContain('class="chip fail"')
  })
  it('puts the one-sentence plain reading first and the method inside a closed disclosure', () => {
    const html = renderToStaticMarkup(<Gates manifest={validateB as unknown as ValidateManifest} runId="abcd00000000beef" />)
    expect(html.match(/<details class="explain-how">/g)?.length).toBe(5)
    expect(html.match(/How this check works/g)?.length).toBe(5)
    expect(html).not.toMatch(/<details[^>]* open/)
    expect(html.indexOf('class="explain-plain"')).toBeLessThan(html.indexOf('class="stat-chips"'))
    expect(html).toMatch(/Random data did as well in [\d.]+% to [\d.]+% of draws/)
    for (const story of gateStories(validateB as unknown as ValidateManifest)) {
      expect(html).toContain(story.tests.slice(0, 40))
      expect(html).toContain(story.narrative.slice(0, 40).replaceAll("'", '&#x27;'))
    }
  })
  it('shows only fact checks with a state word and says not computed when a statistic has no input', () => {
    const stories = gateStories({ outcomes: [] } as unknown as ValidateManifest)
    expect(stories.map(story => story.kind)).toEqual(['fact', 'stat', 'stat', 'stat', 'stat'])
    for (const story of stories.slice(1)) {
      expect(story.state).toBeNull()
      expect(story.plain).toMatch(/^not computed: .+/)
      expect(story.oldLevel).toBeNull()
    }
    expect(stories[0].state).toBe('not-checked')
  })
  it('never colours a gate card good or bad', () => {
    for (const story of gateStories(validateB as unknown as ValidateManifest)) expect(story.tone).toBe('info')
    expect(renderToStaticMarkup(<ExplainCard story={gateStories(validateB as unknown as ValidateManifest)[1]} title="t" />)).not.toMatch(/tone-(good|bad)/)
  })
})

describe('the Stress test and risk terms', () => {
  it('explains the risk terms without a grade', () => {
    for (const key of ['sharpe', 'max_drawdown', 'value_at_risk', 'expected_shortfall', 'risk_of_ruin', 'convention_divergence', 'null_test', 'verdict', 'monte_carlo']) {
      const entry = GLOSSARY[key]
      if (!entry) continue
      assertOwnerText(`<p>${entry.name}</p><p>${entry.short}</p><p>${entry.long}</p>`)
    }
  })
})

describe('toasts and command palette', () => {
  it.each(runs)('show the evidence word, never a grade or gate result, for %s', (_name, run) => {
    assertOwnerText(`<p>${toastDetail(run)}</p>`)
    assertOwnerText(`<p>${paletteHint(run)}</p>`)
  })
  it('names the word and keeps the label', () => {
    expect(toastDetail(runs[2][1])).toBe('synthetic — some evidence')
    expect(paletteHint(runs[0][1])).toBe('runs · synthetic · graded C under the old rules')
    expect(toastDetail({ ...base, label: null, evidence: null, verdict: null, passed: true } as RunListItem)).toBe('')
  })
})

describe('the edge review', () => {
  it('shows a Reading row and no verdict or gate-result row', () => {
    for (const manifest of [{ verdict: { overall: 'B' }, passed: true }, { reading: SOME, verdict: { overall: 'B' }, passed: false }]) {
      const rows = edgeReviewRows(manifest, null)
      expect(rows.map(row => row.label)).not.toContain('Validation verdict')
      expect(rows.map(row => row.label)).not.toContain('Recorded gate result')
      assertOwnerText(rows.map(row => `<td>${row.label}</td><td>${row.value}</td>`).join(''))
    }
    expect(edgeReviewRows({ reading: SOME }, null).find(row => row.label === 'Reading')?.value).toBe('some evidence')
    expect(edgeReviewRows({ verdict: { overall: 'B' } }, null).find(row => row.label === 'Reading')?.value).toBe('graded B under the old rules')
  })
  it('is live: the scan catches a verdict and a lone letter', () => {
    expect(() => assertOwnerText('<td>Validation verdict</td><td>B</td>')).toThrow()
    expect(() => assertOwnerText('<td>Result</td><td>PASS</td>')).toThrow()
  })
})
