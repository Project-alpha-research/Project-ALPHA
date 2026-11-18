import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import type { components } from '../api/generated'
import { statusSentence, labelSentence, endingSentence, directionSentence, clockSentence, verdictNumbers, glossary, storySummary, runOutcome } from './rdagentStory'

type Schema = components['schemas']
const fact = (value: Schema['RecordedFact']['value']): Schema['RecordedFact'] => ({ value })
const factor: Schema['RdAgentFactor'] = {
  name: fact('synthetic'), description: fact('Synthetic only.'), status: 'SCREEN_FAIL', sentence: '',
  idea_families: fact(null), failure_reason: fact(null), figures: { primary_clock: fact('weekly'), screen_rule: fact('alpha-investing-simple-1') },
  clocks: { weekly: {
    figures: { p: fact(0.26), screen_cutoff: fact(0.0004) }, screen: { effective_n: fact(27) },
    spread: { top_third_mean_return: fact(-0.02), bottom_third_mean_return: fact(0.01), mean_spread: fact(-0.03) },
    replay: { net_annual_excess: fact(-0.04), gross_annual_excess: fact(0.01) },
    deflation: { dsr: fact(0.7), threshold: fact(0.95), n_trials: fact(18) }, family_deflation: {},
  } },
}

describe('recorded RD-Agent stories', () => {
  it('has a sentence for every backend status and fails loud on new vocabulary', () => {
    const source = readFileSync('../src/alpha_web/_rdagent_runs.py', 'utf8')
    const block = source.split('STATUS_SENTENCES = {')[1].split('\n}')[0]
    const statuses = [...block.matchAll(/^    "([^"]+)":/gm)].map(match => match[1])
    expect(statuses.length).toBeGreaterThan(20)
    for (const status of statuses) expect(statusSentence(status)).toMatch(/[.!]$/)
    const writer = readFileSync('../../alpha-cli/src/alpha_cli/rdagent_factor_eval.py', 'utf8')
    for (const match of writer.matchAll(/eligibility="([^"]+)"/g)) expect(labelSentence(match[1])).toBeTruthy()
    const judge = readFileSync('../../alpha-cli/src/alpha_cli/_rdagent_judge.py', 'utf8')
    expect(labelSentence(judge.match(/^LABEL = "([^"]+)"/m)![1])).toBeTruthy()
    const ideaSource = source.split('def _idea(')[1].split('labels = []')[1].split('if factor is not None:')[0]
    for (const group of ideaSource.matchAll(/for key in \(([^)]+)\)/g)) {
      for (const match of group[1].matchAll(/"([^"]+)"/g)) expect(labelSentence(match[1])).toBeTruthy()
    }
    for (const match of ideaSource.matchAll(/labels.append\("([^"]+)"\)/g)) expect(labelSentence(match[1])).toBeTruthy()
    const endings = source.split('def _story_ending(')[1].split('\n\ndef ')[0]
    for (const match of endings.matchAll(/(?:return |else )"([^"]+)"/g)) expect(endingSentence(match[1])).toBeTruthy()
    for (const value of ['unknown', '__proto__', 'constructor']) {
      expect(() => statusSentence(value)).toThrow()
      expect(() => labelSentence(value)).toThrow()
      expect(() => endingSentence(value)).toThrow()
    }
  })

  it('explains labels, clocks and declarations without implying a pass', () => {
    expect(labelSentence('shortlist')).toContain('not a pass')
    expect(labelSentence('perp-funding')).toContain('funding')
    expect(labelSentence('composite_suspect')).toContain('earlier')
    expect(labelSentence('diagnostic clocks')).toContain('cannot pass')
    expect(directionSentence(1)).toContain('high')
    expect(directionSentence(-1)).toContain('low')
    expect(directionSentence(null)).toContain('not recorded')
    expect(clockSentence('weekly')).toContain('seven')
    expect(clockSentence('monthly')).toContain('28')
    expect(clockSentence('daily')).toContain('day')
    expect(clockSentence(null)).toContain('not recorded')
    expect(() => clockSentence('new')).toThrow()
    expect(() => directionSentence(0)).toThrow()
    expect(Object.keys(glossary)).toHaveLength(12)
  })

  it('explains every run ending distinctly', () => {
    for (const ending of ['finished', 'budget', 'provider', 'internal_error', 'error', 'not_recorded']) {
      expect(endingSentence(ending)).toMatch(/[.!]$/)
    }
    expect(endingSentence('provider')).toContain('provider')
    expect(endingSentence('internal_error')).toContain('internal')
    expect(runOutcome('completed')).toContain('finished')
    expect(runOutcome('error')).toContain('error')
    expect(runOutcome('stopped by a cap')).toContain('budget')
    expect(runOutcome(null)).toContain('not recorded')
    expect(() => runOutcome('new')).toThrow()
  })

  it('does not turn absent evidence into figures or zeroes', () => {
    expect(verdictNumbers(null)).toEqual([])
    expect(storySummary(null, null)).toHaveLength(6)
    expect(storySummary(null, null).map(sentence => sentence.map(part => part.text).join('')).join(' ')).toContain('not recorded')
  })

  it('quotes stored deciding figures, thresholds and units without recomputing a verdict', () => {
    const screen = verdictNumbers(factor)
    expect(screen.map(number => number.value)).toEqual(['0.26', '27'])
    expect(screen[0].gloss).toContain('0.0004')
    expect(screen[0].gloss).toContain('half the recorded cutoff')
    expect(screen[0].gloss).not.toContain('chance this is luck')
    expect(verdictNumbers({ ...factor, status: 'SPREAD_FAIL' }).map(number => number.value)).toEqual(['-0.02', '0.01', '-0.03'])
    const deflation = verdictNumbers({ ...factor, status: 'DEFLATION_FAIL' })
    expect(deflation.map(number => number.value)).toEqual(['0.7', '18'])
    expect(deflation[0].gloss).toContain('0.95')
    expect(verdictNumbers({ ...factor, status: 'REPLAY_FAIL' }).map(number => number.value)).toEqual(['-0.04', '0.01'])
    expect(verdictNumbers({ ...factor, status: 'CANDIDATE' }).map(number => number.value)).toEqual(['0.26', '-0.04', '0.7'])
  })

  it('does not present counted-only replay returns as results or guess a missing clock', () => {
    const counted = { ...factor, status: 'CANDIDATE', clocks: { weekly: { ...factor.clocks.weekly,
      replay: { ...factor.clocks.weekly.replay, counted_only: fact('not a result') } } } }
    expect(verdictNumbers(counted).some(number => number.label.includes('return'))).toBe(false)
    expect(verdictNumbers({ ...factor, figures: {} })).toEqual([])
    expect(verdictNumbers({ ...factor, clocks: {} })).toEqual([])
    expect(verdictNumbers({ ...factor, status: 'ERROR' })).toEqual([])
    const missing = { ...factor, clocks: { weekly: { figures: {}, screen: {}, spread: {}, replay: {}, deflation: {}, family_deflation: {} } } }
    expect(verdictNumbers(missing).map(number => number.value)).toEqual(['not recorded', 'not recorded'])
  })
})
