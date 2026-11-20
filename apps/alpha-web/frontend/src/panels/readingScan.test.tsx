import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { RuleTest, RuleTestChecks } from '../api/types'
import { CLEAR, FAULT, NO_AIM, NOT_CLEAR, SOME, TOO_LITTLE, WITHIN } from './__fixtures__/readings'
import { BANNED } from './__fixtures__/scanWords'
import { RuleTestReport } from './rundetail/RuleTestReport'
import { SetupLabView, type SetupDetail } from './SetupLabPanel'

// The owner-facing words that left these screens, and a lone letter grade. Fact checks (data health,
// audit rows) keep their own words; the fixtures below carry none, so the scan sees the reading only.
const OLD_PHRASE = /graded [A-F] under the old rules/g
const LETTER = /(?<![\w'./-])[A-F](?![\w'./-])/
const ARTICLE = /(?:^|(?<=[.!?:] ))A(?= [a-z])/gm

function words(html: string): string {
  return html.replace(/<style[\s\S]*?<\/style>/g, '').replace(/<[^>]+>/g, '\n').replaceAll('&amp;', '&').replaceAll('&#x27;', "'")
}
// A pattern match the detector turned away is "rejected" on the find part of Setup Lab. That is a fact about
// a match, not a word about a result, so the find part is scanned without that one word.
function assertOwnerText(html: string, banned: RegExp = BANNED): void {
  const text = words(html).replace(OLD_PHRASE, '')
  expect(text.match(banned)?.[0]).toBeUndefined()
  expect(ARTICLE[Symbol.replace](text, '').match(LETTER)?.[0]).toBeUndefined()
}

const test: RuleTest = {
  idea: 'Buy after a breakout', rule_sentence: 'Hold after a new high', rule_kind: 'breakout', rule_params: {},
  symbol: 'TEST', first_ts: '2020-01-01', last_ts: '2021-12-31', name: null, store: null, source: null,
  labels: ['exploratory', 'quick'], test_id: null, n_bars: null, fee_bps: null, slippage_bps: null, total_trials: null,
  diagnostics_reason: 'not stored', diagnostics: null,
}
const checks = (reading: Record<string, unknown> | null): RuleTestChecks => ({
  run_id: 'abcd00000000beef', reading, checks: [{ tool: 'market.vol_regimes', outcome: 'ok', reading: 'Calm months made 90% of the return.',
    error: null, labels: ['declared'], recorded_at: '2026-11-19T10:00:00+00:00', status: 'declared' }],
  counts: { total: 1, declared: 1, exploratory: 0, text: '1 check run on this result: 1 declared, 0 exploratory' },
})
const oldRun = { verdict: { edge: 'B', robustness: 'B', risk: 'B', sample: 'B', overall: 'C', detail: {}, labels: ['too-few-trades'] }, n_trades: 4 }
const report = (value: RuleTestChecks | string, manifest: object = oldRun) =>
  renderToStaticMarkup(<RuleTestReport test={test} manifest={manifest} runId="abcd00000000beef" figures={[]} checks={value} />)

describe('the rule-test report screen', () => {
  it.each([['some evidence', SOME], ['clear of chance', CLEAR], ['not clear of chance', NOT_CLEAR], ['too little to read', TOO_LITTLE],
    ['no aim row', NO_AIM], ['within the aim', WITHIN], ['a fault', FAULT]])('says no grade, verdict or outcome word with %s', (_name, reading) => {
    assertOwnerText(report(checks(reading)))
  })
  it('keeps the old letter out of every part but the muted old-rules line', () => {
    assertOwnerText(report(checks(null)))
    expect(report(checks(null))).toContain('graded C under the old rules')
    assertOwnerText(report('HTTP 500'))
  })
  it('shows the audit rows of the fact checks as sound, flag or not checked, never pass or fail', () => {
    const audited = { ...test, diagnostics: { flags: [], audit: [
      { check: 'fills-after-decisions', status: 'PASS', detail: '0 of 9 fills lack an earlier decision.' },
      { check: 'enough-trades', status: 'FLAG', detail: '4 closed trades; threshold 30.' },
      { check: 'artifacts-intact', status: 'NOT-CHECKED', detail: 'Not verified yet.' },
    ] } } as unknown as RuleTest
    const html = renderToStaticMarkup(<RuleTestReport test={audited} manifest={oldRun} runId="abcd00000000beef" figures={[]} checks={checks(SOME)} />)
    assertOwnerText(html)
    for (const word of ['>sound<', '>flag<', '>not checked<']) expect(html).toContain(word)
  })
  it('catches a lone letter grade and the banned words (the scan is live)', () => {
    expect(() => assertOwnerText('<td>SPY</td><td>C</td>')).toThrow()
    expect(() => assertOwnerText('<p>This idea is supported.</p>')).toThrow()
    expect(() => assertOwnerText('<p>Verdict: B</p>')).toThrow()
    expect(() => assertOwnerText('<p>A result of 0.4. graded B under the old rules</p>')).not.toThrow()
  })
})

const old = (outcome: string): Record<string, unknown> => ({ outcome, occurrences: 41, reading: 'After this setup the average 5-bar return was 0.41% after costs.' })
const outcome = (id: string, summary: Record<string, unknown>, reading: SetupDetail['studies'][number]['reading']) => ({
  run_id: id, rule_version: 'setup-study-2', summary, rows: [], figure: { name: 'event-study.png', png: null }, labels: ['exploratory'],
  trial_indices: [2], reading,
})
const detail: SetupDetail = {
  run: { find_id: 'a'.repeat(16), name: 'Synthetic pullback', description: 'A synthetic pullback after a rise.', recorded_at: '2026-11-01T00:00:00Z',
    assets: [{ asset: 'SYN', first_bar: '2020-01-01T00:00:00Z', last_bar: '2026-10-31T00:00:00Z' }], labels: [] },
  summary: { totals: { accepted: 1, rejected: 1 } }, spec: null, candidates: [], price_bars: null, price_bars_reason: 'Price bars: not recorded.',
  sheets: [], trial_indices: [1], limits: ['Daily bars only.'], label_explanations: {},
  studies: [
    outcome('b'.repeat(16), { ...old('not supported'), evidence: 'not clear of chance' }, { evidence: 'not clear of chance', old_wording: false, family_position: 2, family_count: 3 }),
    outcome('d'.repeat(16), old('supported (exploratory, not confirmed)'), { evidence: 'some evidence', old_wording: true, family_position: 1, family_count: 3 }),
    outcome('e'.repeat(16), old('inconclusive'), { evidence: 'too little to read', old_wording: true, family_position: null, family_count: 3 }),
  ],
  trades: [outcome('c'.repeat(16), { outcome: 'not supported', pooled: { trades: 41, mean: 0.01 }, reading: 'Traded with these exits the average trade made 1.00%.' },
    { evidence: 'not clear of chance', old_wording: true, family_position: 1, family_count: 1 })],
}
const setup = renderToStaticMarkup(<SetupLabView list={{ items: [detail.run] }} selected={detail.run.find_id} detail={detail} error={null} onSelect={() => undefined} />)

describe('the Setup Lab screen', () => {
  it('says no outcome word, grade or verdict, even for old records that stored one', () => {
    const results = setup.slice(setup.indexOf('aria-label="Recorded event study"'), setup.indexOf('<aside'))
    expect(results.length).toBeGreaterThan(1000)
    assertOwnerText(results)
    assertOwnerText(setup, /\b(supported|inconclusive|verdict|grade)\b/i)
  })
  it('shows the evidence word with the scale, the family line and old wording where only the old word was stored', () => {
    expect(setup).toContain('Evidence strength: not clear of chance<')
    expect(setup).toContain('Evidence strength: some evidence (old wording)')
    expect(setup).toContain('Evidence strength: too little to read (old wording)')
    expect(setup).toContain('Setup study 2 of 3 recorded for this idea.')
    expect(setup).toContain('Setup study: not among the 3 studies recorded for this idea.')
    expect(setup).toContain('Setup trade 1 of 1 recorded for this idea.')
    expect(setup.match(/aria-current="step"/g)).toHaveLength(4)
  })
})
