import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import type { RuleTest, RuleTestChecks } from '../../api/types'
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
      labels: ['ad-hoc', 'reserved-period-seen'], recorded_at: '2026-11-19T10:00:00+00:00' },
    { tool: 'market.attribution', outcome: 'error', reading: null, error: 'UNKNOWN_ASSET',
      labels: ['ad-hoc'], recorded_at: '2026-11-19T09:00:00+00:00' },
  ],
}
const render = (checks?: RuleTestChecks | string | null): string =>
  renderToStaticMarkup(<RuleTestReport test={test} manifest={{}} runId="abcd00000000beef" figures={[]} checks={checks} />)

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
