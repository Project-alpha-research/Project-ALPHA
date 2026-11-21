// The explanation engine's guardrails: gate, suggestion and kind-module stories.

import { describe, expect, it } from 'vitest'

import { forecastStories } from './forecast'
import { gateStories, nullStory, walkForwardStory } from './gates'
import { optimStories, optimSuggestions } from './optim'
import { portfolioStories } from './portfolio'
import { propfirmStories } from './propfirm'
import { suggestions } from './suggestions'
import type { OptimManifest, PortfolioManifest, PropfirmManifest, ValidateManifest } from './types'
import optimFixture from './__fixtures__/optim.json'
import portfolioFixture from './__fixtures__/portfolio.json'
import propfirmFixture from './__fixtures__/propfirm.json'
import validateB from './__fixtures__/validate-b.json'

describe('gate stories', () => {
  const m = validateB as unknown as ValidateManifest

  it('produces all five gates in canonical order', () => {
    expect(gateStories(m).map((g) => g.gate)).toEqual([
      'walk_forward_oos',
      'randomized_price_null',
      'bootstrap_ci',
      'deflated_sharpe',
      'cpcv_oos',
    ])
  })

  it('every story carries both voices and teaching text', () => {
    for (const g of gateStories(m)) {
      expect(g.narrative.length).toBeGreaterThan(80)
      expect(g.terse.length).toBeGreaterThan(5)
      expect(g.tests.length).toBeGreaterThan(40)
    }
  })

  it('walk-forward counts folds and flat windows', () => {
    const g = walkForwardStory(m)
    expect(g.passed).toBe(true)
    expect(g.terse).toContain('31 folds')
    // fold 24 is flat (null sharpe) → 30 graded
    expect(g.terse).toContain('of 31')
  })

  it('walk-forward says why the window count and the above-zero count differ', () => {
    const fold = (index: number, sharpe: number | null) => ({ index, n_test: 252, oos_sharpe: sharpe })
    const folds = [fold(0, 1.2), fold(1, 0.4), fold(2, 0.1), fold(3, -0.3), fold(4, -0.1), fold(5, null), fold(6, null)]
    const g = walkForwardStory({ ...m, folds, oos_metrics: { ...m.oos_metrics, sharpe: 0.16 } } as unknown as ValidateManifest)
    expect(g.plain).toBe(
      'The out-of-sample Sharpe is 0.16 over 7 windows. 3 windows were above zero, 2 were at or below zero, ' +
        'and 2 had no Sharpe recorded.',
    )
    expect(g.stats.find((s) => s.label === 'Folds above zero')?.value).toBe('3 of 7 (2 with no Sharpe)')
    expect(g.terse).toContain('3 of 7 above zero (2 with no Sharpe)')
    expect(g.narrative).toContain('3 of 7 windows had a positive Sharpe (2 with no Sharpe recorded)')
  })

  it('walk-forward stays short when every window has a Sharpe', () => {
    const fold = (index: number, sharpe: number) => ({ index, n_test: 252, oos_sharpe: sharpe })
    const folds = [fold(0, 1.2), fold(1, -0.3), fold(2, 0.5)]
    const g = walkForwardStory({ ...m, folds, oos_metrics: { ...m.oos_metrics, sharpe: 0.5 } } as unknown as ValidateManifest)
    expect(g.plain).toBe('The out-of-sample Sharpe is 0.50 over 3 windows, with 2 of 3 windows above zero.')
    expect(g.stats.find((s) => s.label === 'Folds above zero')?.value).toBe('2 of 3')
  })

  it('a null gate that random data matched reads as luck, in numbers, without a colour or a pass word', () => {
    const g = nullStory(m)
    expect(g.passed).toBe(false)
    expect(g.kind).toBe('stat')
    expect(g.tone).toBe('info')
    expect(g.narrative).toContain('cannot be told apart from luck')
    expect(g.narrative).toContain('random data did as well in 53.8% of draws')
    expect(g.oldLevel).toBe('The level used by the old grade: each tier at the 95% percentile or higher')
  })

  it('classes walk-forward as a fact check and the other four as statistics', () => {
    const stories = gateStories(m)
    expect(stories.map((g) => g.kind)).toEqual(['fact', 'stat', 'stat', 'stat', 'stat'])
    expect(stories[0].state).toBe('sound')
    expect(stories.slice(1).every((g) => g.state === null && g.oldLevel !== null)).toBe(true)
    expect(stories.every((g) => g.tone === 'info')).toBe(true)
    expect(JSON.stringify(stories.map((g) => [g.terse, g.narrative, g.tests]))).not.toMatch(/\b(pass|passed|fail|failed|verdict)\b/i)
  })

  it('shows the interval as a number and a plain comparison', () => {
    const g = gateStories(m)[2]
    expect(g.terse).toMatch(/the interval includes zero$/)
    expect(g.oldLevel).toBe('The level used by the old grade: lower end above 0')
  })
})

describe('suggestions', () => {
  it('failed-null run leads with the luck suggestion', () => {
    const s = suggestions(validateB as unknown as ValidateManifest)
    expect(s.length).toBeGreaterThan(0)
    expect(s[0].title).toContain('luck')
  })
  it('CI straddling zero yields the statistical-power suggestion', () => {
    const s = suggestions(validateB as unknown as ValidateManifest)
    expect(s.some((x) => x.title.includes('straddles zero'))).toBe(true)
  })
})

describe('kind modules', () => {
  it('optim: all three control stories, passing sweep suggests validate', () => {
    const m = optimFixture as unknown as OptimManifest
    const stories = optimStories(m)
    expect(stories.map((s) => s.title)).toEqual([
      'Deflated Sharpe (best of the sweep)',
      'Probability of backtest overfitting',
      'Data-snooping tests (Reality Check / SPA)',
    ])
    const sugg = optimSuggestions(m)
    expect(sugg[0].action?.command).toBe('validate')
  })

  it('propfirm: odds + EV stories with money formatting', () => {
    const stories = propfirmStories(propfirmFixture as unknown as PropfirmManifest)
    expect(stories).toHaveLength(2)
    expect(stories[0].terse).toMatch(/pass \d+%/)
    expect(stories[1].stats[0].value).toMatch(/^[$—-]/)
  })

  it('portfolio: headline + diversification check', () => {
    const stories = portfolioStories(portfolioFixture as unknown as PortfolioManifest)
    expect(stories.length).toBeGreaterThanOrEqual(2)
    expect(stories[1].title).toBe('Diversification check')
  })

  it('forecast: eval summaries split honest vs overlapping', () => {
    const stories = forecastStories({
      command: 'forecast_eval',
      summary_post_cutoff: { n_origins: 10, skill_vs_rw: -0.05, skill_vs_bootstrap: -0.1, coverage80: 0.9, hit_rate: 0.4 },
      summary_pre_cutoff: { n_origins: 20, skill_vs_rw: 0.2, skill_vs_bootstrap: 0.1, coverage80: 0.8, hit_rate: 0.6 },
    })
    const post = stories.find((s) => s.title.includes('Post-cutoff'))
    expect(post?.tone).toBe('bad')
    const pre = stories.find((s) => s.title.includes('Pre-cutoff'))
    expect(pre?.tone).toBe('warn')
  })
})
