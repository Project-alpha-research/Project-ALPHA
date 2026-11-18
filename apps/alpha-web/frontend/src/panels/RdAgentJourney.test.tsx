import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { MissingJourney, RdAgentJourney, type Journey } from './RdAgentJourney'

const steps = ['Idea', 'Calculation', 'Leak check', 'Quick test', 'Trading test', 'Feedback', 'Limits']
const document: Journey = {
  iteration: 0, name: 'Synthetic factor', code_sha256: 'a'.repeat(64), figures: {},
  steps: steps.map((title, i) => ({
    title, who: [0, 1, 5].includes(i) ? 'RD-Agent (AI)' : 'ALPHA rule',
    text: 'Stored paragraph.', what_this_means: 'Stored interpretation.',
    source: ['evaluations/iter-0/result.json'], numbers: [],
    ...(i === 1 ? { code: Array.from({ length: 14 }, (_, n) => 'line ' + (n + 1)).join('\n'), figure: 'signal.png' } : {}),
    ...(i === 0 ? { own_words: 'Recorded wording.' } : {}),
    ...(i === 3 ? { numbers: [{ label: 'Sample', value: 0, display: '0.0%', gloss: 'Stored gloss.' }] } : {}),
    ...(i === 4 ? { figure_reason: 'No replay was run.' } : {}),
    ...(i === 6 ? { facts: ['Coverage was limited.', 'Stored exploratory label.'] } : {}),
  })),
}

describe('the stored idea journey', () => {
  it('shows the label above seven ordered steps with attribution, meaning and visible gloss', () => {
    const html = renderToStaticMarkup(<RdAgentJourney journey={document} base="/synthetic" />)
    expect(html.indexOf('Stored exploratory label.')).toBeLessThan(html.indexOf('1. Idea'))
    expect(html).toContain('Synthetic factor')
    for (const [i, title] of steps.entries()) expect(html).toContain(`${i + 1}. ${title}`)
    expect(html.match(/Stored paragraph\./g)).toHaveLength(7)
    expect(html.match(/Stored interpretation\./g)).toHaveLength(7)
    for (const text of ['RD-Agent (AI)', 'ALPHA rule', '0.0%', 'Sample', 'Stored gloss.', 'Coverage was limited.']) expect(html).toContain(text)
    expect(html).toMatch(/<dd[^>]*>[\s\S]*Stored gloss\.<\/span><\/dd>/)
    expect(html).toContain('src="/synthetic/figures/signal.png"')
    expect(html).toContain('data-theme="light"')
    expect(html).toContain('No replay was run.')
  })

  it('shows the exact build command and identifies a run-wide build for an unlinked idea', () => {
    const result = { reason: 'Journey not built yet' as const, command: "uv run alpha ledger journey --run-dir 'synthetic run'" }
    const idea = { id: 'task-0', name: 'Proposal', built: false, iteration: null, verdict: null }
    const html = renderToStaticMarkup(<MissingJourney idea={idea} result={result} />)
    expect(html).toContain('Journey not built yet')
    expect(html).toContain('A judged evaluation is not recorded for this idea.')
    expect(html).toContain('<code>uv run alpha ledger journey --run-dir &#x27;synthetic run&#x27;</code>')
  })

  it('keeps sources, agent wording and code after line twelve behind closed disclosures', () => {
    const html = renderToStaticMarkup(<RdAgentJourney journey={document} base="/synthetic" />)
    expect(html).toMatch(/<details><summary>Show the agent(?:&#x27;|’)s own words<\/summary>[\s\S]*?Recorded wording\./)
    expect(html).toMatch(/<details><summary>Where this comes from<\/summary>[\s\S]*?evaluations\/iter-0\/result.json/)
    expect(html).toMatch(/line 12<\/code><\/pre><details><summary>[^<]+<\/summary><pre><code>line 13\nline 14/)
    expect(html).not.toContain('<details open')
    expect(html).toContain('not recorded')
  })
})
