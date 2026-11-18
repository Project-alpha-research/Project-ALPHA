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
  it('shows a linked story, round cards, explanations and raw rows only inside technical detail', () => {
    const idea = {
      id: 'trial-0', round: fact(2), round_kind: 'evaluation' as const,
      name: fact('Synthetic idea'), description: fact('The proposer’s own words.'),
      direction: fact(-1), clock: fact('weekly'), reason: fact('A stored economic reason.'),
      system_statuses: ['coded'], refusal: fact(), feedback: fact('Try a different mechanism.'),
      feedback_scope: 'round' as const, trial: detail.factors[0],
      stages: { proposed: true, refused: false, coded: true, ran: true, judged: true, shortlisted: true, candidate: true },
      labels: ['shortlist', 'perp-funding', 'composite_suspect', 'diagnostic clocks'],
      code_file: fact('synthetic.py'), raw: '{"raw_marker":"technical only"}',
    }
    const story = { ideas: [idea], journey: Object.fromEntries(Object.entries(idea.stages).map(([key, value]) => [key, fact(value ? 1 : 0)])),
      missing_links: [], ending: 'finished', ending_reason: fact('completed'), minutes: fact(2) }
    const html = renderToStaticMarkup(<RdAgentView list={{ items: [run], reason: null, ledger_reason: null }} selected="first" detail={{ ...detail, story }} error={null} onSelect={() => undefined} />)
    for (const text of ['What happened in this run', 'Idea journey', 'The proposer’s own words.',
      'What the system did', 'What the test said', 'What it was told next', 'Try a different mechanism.',
      'not a pass', 'funding coverage', 'earlier tries', 'cannot pass', 'Words used here']) expect(html).toContain(text)
    for (const stage of Object.keys(idea.stages)) {
      expect(html).toContain(`id="journey-${stage}"`)
      expect(html).toContain(`href="#journey-${stage}"`)
    }
    expect(html).toContain('href="#idea-trial-0"')
    expect(html).toContain('id="idea-trial-0"')
    expect(html).toMatch(/<details[^>]*><summary>technical detail<\/summary>[\s\S]*raw_marker/)
    expect(html.indexOf('What the system did')).toBeLessThan(html.indexOf('What the test said'))
    expect(html.indexOf('What the test said')).toBeLessThan(html.indexOf('What it was told next'))
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
  it('shows a round\'s feedback once and points later cards of that round to it', () => {
    const base = {
      round: fact(0), round_kind: 'evaluation' as const, description: fact(), direction: fact(), clock: fact(), reason: fact(),
      system_statuses: ['coded'], refusal: fact(), feedback: fact('Synthetic round feedback.'), feedback_scope: 'round' as const,
      trial: null, stages: { proposed: true, refused: false, coded: true, ran: true, judged: true, shortlisted: false, candidate: false },
      labels: [], code_file: fact(), raw: '{}',
    }
    const story = {
      ideas: [{ ...base, id: 'a', name: fact('First synthetic') }, { ...base, id: 'b', name: fact('Second synthetic') }],
      journey: {}, missing_links: [], ending: 'finished', ending_reason: fact(), minutes: fact(), events: [],
    }
    const html = renderToStaticMarkup(<RdAgentView list={{ items: [run], reason: null, ledger_reason: null }} selected="first" detail={{ ...detail, story }} error={null} onSelect={() => undefined} />)
    expect(html.split('Synthetic round feedback.').length - 1).toBe(1)
    expect(html).toContain('The same feedback as for First synthetic above')
  })
})
