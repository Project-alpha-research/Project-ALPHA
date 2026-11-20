import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { RuleTest, RuleTestChecks } from '../../api/types'
import { FAULT, SOME } from '../__fixtures__/readings'
import { RuleTestReport } from './RuleTestReport'

const test: RuleTest = {
  idea: 'Buy after a breakout', rule_sentence: 'Hold after a new high', rule_kind: 'breakout', rule_params: {},
  symbol: 'TEST', first_ts: '2020-01-01', last_ts: '2021-12-31', name: null, store: null, source: null,
  labels: ['exploratory'], test_id: null, n_bars: null, fee_bps: null, slippage_bps: null, total_trials: null,
  diagnostics_reason: 'not stored', diagnostics: null,
}
const READING = 'Calm months made 90% of the return; turbulent months made 10%.'
const stored: RuleTestChecks = {
  run_id: 'abcd00000000beef',
  checks: [
    { tool: 'market.vol_regimes', outcome: 'ok', reading: READING, error: null,
      labels: ['ad-hoc', 'reserved-period-seen'], recorded_at: '2026-11-19T10:00:00+00:00', status: 'exploratory' },
    { tool: 'market.attribution', outcome: 'error', reading: null, error: 'UNKNOWN_ASSET',
      labels: ['ad-hoc'], recorded_at: '2026-11-19T09:00:00+00:00', status: null },
  ],
  reading: SOME,
  counts: { total: 1, declared: 0, exploratory: 1, text: '1 check run on this result: 0 declared, 1 exploratory' },
}
const render = (checks?: RuleTestChecks | string | null, manifest: object = {}): string =>
  renderToStaticMarkup(<RuleTestReport test={test} manifest={manifest} runId="abcd00000000beef" figures={[]} checks={checks} />)

describe('Checks run on this test', () => {
  it('shows each stored reading unedited with its labels explained and its time', () => {
    const html = render(stored)
    expect(html).toContain('Checks run on this test')
    expect(html).toContain('Calm and turbulent markets')
    expect(html).toContain(READING)
    expect(html).toContain('Run on its own, not as part of a predeclared set of checks.')
    expect(html).toContain('The data reaches into the reserved period, which starts on 2024-01-01.')
    expect(html).toMatch(/<time title="2026-11-19T10:00:00\+00:00">/)
  })

  it('leaves out labels the test itself carries', () => {
    const html = render({ run_id: 'x', checks: [{ ...stored.checks[0], labels: ['exploratory', 'ad-hoc'] }] })
    const section = (html.split('Checks run on this test').at(-1) ?? '').split('</section>')[0]
    expect(section).not.toContain('Exploratory test.')
    expect(section).toContain('ad-hoc')
  })

  it('shows an error row as could not run', () => {
    expect(render(stored)).toContain('could not run: UNKNOWN_ASSET')
  })

  it('says none were run and gives the standard set command', () => {
    const html = render({ run_id: 'abcd00000000beef', checks: [] })
    expect(html).toContain('No checks have been run on this test yet.')
    expect(html).toContain('alpha tool run-set market-context abcd00000000beef')
  })

  it('shows loading and failure states, and nothing when no checks were passed', () => {
    expect(render(null)).toContain('Loading checks')
    expect(render('HTTP 422')).toContain('Could not load the checks. HTTP 422')
    expect(render(undefined)).not.toContain('Checks run on this test')
  })
})

describe('Tool results: declared or exploratory', () => {
  it('shows each result’s word as a small neutral chip and the count line', () => {
    const html = render({ ...stored, checks: [stored.checks[0], { ...stored.checks[0], tool: 'market.changepoints', status: 'declared', labels: ['declared'] }] ,
      counts: { total: 2, declared: 1, exploratory: 1, text: '2 checks run on this result: 1 declared, 1 exploratory' } })
    expect(html).toContain('2 checks run on this result: 1 declared, 1 exploratory')
    expect(html).toMatch(/<span class="chip kind rule-test-status-chip"[^>]*>declared<\/span>/)
    expect(html).toMatch(/<span class="chip kind rule-test-status-chip"[^>]*>exploratory<\/span>/)
    expect(html.match(/>declared</g)).toHaveLength(1)
  })
  it('shows no word for a failed attempt', () => {
    const section = (render(stored).split('Checks run on this test').at(-1) ?? '')
    expect(section.match(/rule-test-status-chip/g)).toHaveLength(1)
  })
})

describe('The reading on the report screen', () => {
  it('shows the relayed reading under the headline', () => {
    const html = render(stored)
    expect(html).toContain('aria-label="Reading"')
    expect(html).toContain('Evidence strength: some evidence')
    expect(html.indexOf('aria-label="Reading"')).toBeLessThan(html.indexOf('Whole period the rule could trade'))
  })
  it('shows a fault instead of a reading', () => {
    const html = render({ ...stored, reading: FAULT })
    expect(html).toContain('Fix this first. No reading.')
    expect(html).not.toContain('Against the aim')
  })
  it('shows the old letter, muted, only when no reading came back', () => {
    const old = { verdict: { overall: 'C' } }
    expect(render({ ...stored, reading: null }, old)).toContain('graded C under the old rules')
    expect(render(stored, old)).not.toContain('graded C')
    expect(render('HTTP 500', old)).toContain('graded C under the old rules')
  })
  it('says it is loading, and shows no block when checks are not asked for', () => {
    expect(render(null)).toContain('Loading the reading')
    expect(render(undefined)).not.toContain('aria-label="Reading"')
  })
})
