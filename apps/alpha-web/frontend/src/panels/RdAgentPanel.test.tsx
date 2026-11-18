import { describe, expect, it, vi, afterEach } from 'vitest'
import * as React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { RdAgentView, RdAgentPanel, type Detail, type Run, type Fact } from './RdAgentPanel'

vi.mock('react', async importOriginal => ({ ...await importOriginal<typeof import('react')>() }))

const fact = (value: Fact['value'] = null): Fact => ({ value, reason: value === null ? 'not recorded by this run' : null, basis: null })
const run: Run = {
  run_id: 'first', folder: 'Recorded run', started_at: fact('2026-11-17T14:33:00Z'), ended_at: fact(),
  outcome: fact('completed'), rounds_completed: fact(2), counted_calls: fact(12),
  local_embedding_calls: fact(3), provider_embedding_calls: fact(), cost_usd: fact(0.2),
  factors_proposed: fact(), stages: {}, universe_size: fact(), universe_includes_delisted: fact(true),
}
const detail: Detail = {
  run, funnel: { proposed: { value: 3, reason: null, basis: 'counted from the recorded factor trials' }, stopped_by_provider: fact(2), passed_deflation: fact() },
  factors: [{ name: fact('slow_rank'), description: fact('Slow relative returns.'),
    status: 'CANDIDATE', sentence: 'Confirmation is still required.', failure_reason: fact(),
    idea_families: fact(), figures: {}, clocks: {} }],
  factor_reason: null, refusals: [], refusal_reason: null, timing: [{ loop: fact(0), step: fact('coding'), started_at: fact('2026-11-01T00:00:00Z'), ended_at: fact('2026-11-01T00:01:00Z'), minutes: fact(1), status: fact('ok') }], timing_reason: null,
  caps: { calls: { used: fact(12), limit: fact(60) }, run_usd: { used: fact(0.2), limit: fact(10) },
    month_usd: { used: fact(1.3), limit: fact(50) } },
  months: {}, cache: { cache_hit_rate: fact(0.6) }, providers: {}, universe: {},
  identity_splits: [], identity_rescales: [], notes: ['Local embeddings are free.'],
}

afterEach(() => { vi.unstubAllGlobals(); vi.restoreAllMocks() })

describe('RD-Agent recorded panel', () => {
  it('lists same-name ideas with their iteration, verdict and publication state', () => {
    const journeys = [
      { id: 'first', name: 'Synthetic', iteration: 1, verdict: 'SCREEN_FAIL', built: true },
      { id: 'second', name: 'Synthetic', iteration: 3, verdict: null, built: false },
    ]
    const html = renderToStaticMarkup(<RdAgentView list={{ items: [run] }} selected="first" detail={{ ...detail, journeys }} error={null} onSelect={() => undefined} />)
    expect(html).toContain('Synthetic · iteration 1 · Failed the quick test. · journey available')
    expect(html).toContain('Synthetic · iteration 3 · not recorded · journey not built yet')
    expect(html).toContain('Loading journey…')
  })

  it('omits unrecorded summary lines and keeps recorded zero counts', () => {
    const story: NonNullable<Detail['story']> = {
      ending: '', ending_reason: fact(), ideas: [], minutes: fact(), missing_links: [],
      journey: { proposed: fact(0), shortlisted: fact() },
    }
    const html = renderToStaticMarkup(<RdAgentView list={{ items: [run] }} selected="first" detail={{ ...detail, story }} error={null} onSelect={() => undefined} />)
    const summary = html.slice(html.indexOf('<main'), html.indexOf('Technical detail for this run'))
    expect(summary).toContain('<dt>outcome</dt>')
    expect(summary).toContain('proposed: 0')
    expect(summary).not.toMatch(/ended at|shortlisted \(not a pass\)|not recorded by this run|This run stored no summary/)
  })

  it('shows one muted empty summary and puts the recorded ledger absence in technical detail', () => {
    const absent = 'The factor trial ledger is absent.'
    const emptyRun = { ...run, outcome: fact(), started_at: fact(), rounds_completed: fact() }
    const html = renderToStaticMarkup(<RdAgentView list={{ items: [emptyRun], ledger_reason: absent }} selected="first" detail={{ ...detail, run: emptyRun, factor_reason: absent }} error={null} onSelect={() => undefined} />)
    expect(html.match(/This run stored no summary\./g)).toHaveLength(1)
    expect(html).toContain('<p class="muted">This run stored no summary.</p>')
    expect(html.match(/The factor trial ledger is absent\./g)).toHaveLength(1)
    expect(html.indexOf(absent)).toBeGreaterThan(html.indexOf('<details><summary>Technical detail for this run</summary>'))

    const present = renderToStaticMarkup(<RdAgentView list={{ items: [run] }} selected="first" detail={detail} error={null} onSelect={() => undefined} />)
    expect(present).not.toContain(absent)
  })

  it('uses terminal panel surfaces and ink instead of figure-canvas colours', () => {
    const html = renderToStaticMarkup(<RdAgentView list={{ items: [run], reason: null, ledger_reason: null }} selected="first" detail={detail} error={null} onSelect={() => undefined} />)
    expect(html).toContain('background:var(--panel)')
    expect(html).toContain('color:var(--ink)')
    expect(html).toContain('background:var(--accent)')
    expect(html).not.toContain('--canvas-')
  })

  it('shows runs, funnel, three labelled meters, factor chips and exploratory notice', () => {
    const html = renderToStaticMarkup(<RdAgentView list={{ items: [run], reason: null, ledger_reason: null }} selected="first" detail={detail} error={null} onSelect={() => undefined} />)
    for (const text of ['Recorded run', 'ideas proposed', 'stopped by the model provider: 2', 'counted from the recorded factor trials', 'survived the multiple-testing check',
      'Calls', 'USD this run', 'USD this month', 'slow_rank', 'CANDIDATE', 'Confirmation is still required.',
      'Exploratory results. Nothing here is evidence of an edge until a candidate is confirmed on reserved data.',
      'Universe', 'Cost and cache', 'Step timing', 'end time minus the start time', 'not recorded by this run']) expect(html).toContain(text)
    expect(html.match(/role="meter"/g)).toHaveLength(3)
    expect(html).toContain('aria-valuenow="12"')
    expect(html).toContain('<details')
    expect(html).toContain('class="chip">CANDIDATE</span>')
  })

  it('renders readable list, detail and step times with their original ISO titles', () => {
    const html = renderToStaticMarkup(<RdAgentView list={{ items: [run], reason: null, ledger_reason: null }} selected="first" detail={detail} error={null} onSelect={() => undefined} />)
    expect(html.match(/title="2026-11-17T14:33:00Z"/g)).toHaveLength(2)
    expect(html.match(/17 Nov 2026, 14:33 UTC/g)).toHaveLength(2)
    expect(html).toContain('title="2026-11-01T00:00:00Z"')
    expect(html).toContain('1 Nov 2026, 00:00 UTC')
    expect(html).toContain('1 min')
  })

  it('selects only the requested run using an encoded read URL', async () => {
    const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => detail })
    vi.stubGlobal('fetch', fetcher)
    vi.spyOn(React, 'useEffect').mockImplementation(effect => { effect() })
    const setDetail = vi.fn()
    const state = vi.spyOn(React, 'useState')
    const select = (id: string) => {
      state.mockReturnValueOnce([null, vi.fn()]).mockReturnValueOnce([id, vi.fn()])
        .mockReturnValueOnce([null, setDetail]).mockReturnValueOnce([null, vi.fn()])
      RdAgentPanel()
    }
    select('first')
    await vi.waitFor(() => expect(setDetail).toHaveBeenCalledWith(detail))
    expect(fetcher).toHaveBeenCalledWith('/api/rdagent/runs/first')
    select('../other')
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalledWith('/api/rdagent/runs/..%2Fother'))
  })

  it('marks counted-only replays before their recorded figures are expanded', () => {
    const clock = { figures: {}, screen: {}, spread: {}, replay: { counted_only: fact('spread check FAIL; not a result'), 'net.annualized_return': fact(0.03) }, deflation: { dsr: fact(0.7), passed: fact(false), n_trials: fact(5) }, family_deflation: {} }
    const recorded = { ...detail, factors: [{ ...detail.factors[0], clocks: { weekly: clock } }] }
    const html = renderToStaticMarkup(<RdAgentView list={{ items: [run], reason: null, ledger_reason: null }} selected="first" detail={recorded} error={null} onSelect={() => undefined} />)
    expect(html).toContain('<strong>Trial accounting only: spread check FAIL; not a result</strong>')
    expect(html).toContain('Deflated Sharpe probability')
    expect(html).toContain('Trials used')
    expect(html).toContain('0.7')
  })

  it('keeps loading, empty and error states distinct', () => {
    const props = { selected: null, detail: null, onSelect: () => undefined }
    const loading = renderToStaticMarkup(<RdAgentView {...props} list={null} error={null} />)
    const empty = renderToStaticMarkup(<RdAgentView {...props} list={{ items: [], reason: 'No recorded runs.', ledger_reason: null }} error={null} />)
    const error = renderToStaticMarkup(<RdAgentView {...props} list={null} error="Records could not be read." />)
    expect(loading).toContain('Loading recorded runs')
    expect(empty).toContain('No recorded runs.')
    expect(error).toContain('role="alert"')
    expect(error).toContain('Records could not be read.')
    expect(error).not.toContain('Loading recorded runs')
    expect(empty).toContain('Exploratory results.')
  })

  it('does not turn missing cap figures into zero meters or show a stale selection', () => {
    const html = renderToStaticMarkup(<RdAgentView list={{ items: [run], reason: null, ledger_reason: null }} selected="first" detail={{ ...detail, caps: { calls: { used: fact(), limit: fact(60) } } }} error={null} onSelect={() => undefined} />)
    expect(html).not.toContain('role="meter"')
    expect(html).toContain('not recorded by this run')
    const pending = renderToStaticMarkup(<RdAgentView list={{ items: [run], reason: null, ledger_reason: null }} selected="second" detail={detail} error={null} onSelect={() => undefined} />)
    expect(pending).not.toContain('slow_rank')
    expect(pending).toContain('Loading recorded run')
  })
})
