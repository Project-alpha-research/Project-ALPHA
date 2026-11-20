import { describe, expect, it } from 'vitest'
import { CLEAR, FAULT, NO_AIM, SOME } from './__fixtures__/readings'
import {
  aimSentence, aimSourceLine, countLines, EVIDENCE_STEPS, evidenceStep, faultText, parseReading, rangePicture,
} from './readingModel'

describe('parseReading', () => {
  it('reads every part of a stored reading', () => {
    const reading = parseReading(SOME)
    expect(reading?.sentence).toContain('Out-of-sample Sharpe 0.75')
    expect(reading?.checks.map(check => check.state)).toEqual(['sound', 'sound', 'not-checked'])
    expect(reading?.evidence.word).toBe('some evidence')
    expect(reading?.aim.rows[0].interval).toEqual([0.1, 1.4])
    expect(reading?.measures[0].interval).toEqual([0.1, 1.4])
    expect(reading?.counts.best_of).toBe(6)
  })
  it('returns null for anything that is not a reading', () => {
    for (const bad of [null, undefined, 3, 'x', [], {}, { sentence: 'a', checks: 'no' }]) expect(parseReading(bad)).toBeNull()
  })
  it('refuses an evidence word that is not one of the four', () => {
    expect(parseReading({ ...SOME, evidence: { word: 'supported', because: [] } })).toBeNull()
  })
  it('keeps the fault and marks its numbers as not to be read', () => {
    const reading = parseReading(FAULT)
    expect(faultText(reading!)).toBe('a fill came at or before its decision (look-ahead)')
    expect(reading?.measures.every(row => row.notToBeRead)).toBe(true)
    expect(faultText(parseReading(SOME)!)).toBeNull()
  })
})

describe('evidence scale', () => {
  it('has four steps in the fixed order and marks the current one', () => {
    expect(EVIDENCE_STEPS).toEqual(['too little to read', 'not clear of chance', 'some evidence', 'clear of chance'])
    expect(evidenceStep('some evidence')).toBe(2)
    expect(evidenceStep('too little to read')).toBe(0)
    expect(evidenceStep('fault')).toBe(-1)
    expect(evidenceStep(null)).toBe(-1)
  })
})

describe('against the aim', () => {
  it('puts the tick outside the bar when the aim is above the interval', () => {
    const picture = rangePicture(parseReading(SOME)!.aim.rows[0])!
    expect(picture.aimInside).toBe(false)
    expect(picture.aim).toBeGreaterThan(picture.right)
    expect(picture.left).toBeGreaterThanOrEqual(0)
    expect(picture.aim).toBeLessThanOrEqual(100)
  })
  it('puts the tick inside the bar when the aim is within the interval', () => {
    const row = { measure: 'm', aim: 0.9, observed: 0.75, interval: [0.1, 1.4] as [number, number], relation: 'within the uncertainty of the aim' }
    const picture = rangePicture(row)!
    expect(picture.aimInside).toBe(true)
    expect(picture.aim).toBeGreaterThan(picture.left)
    expect(picture.aim).toBeLessThan(picture.right)
  })
  it('puts the tick left of the bar when the aim is below the interval', () => {
    const picture = rangePicture(parseReading(CLEAR)!.aim.rows[0])!
    expect(picture.aim).toBeLessThan(picture.left)
    expect(picture.aimInside).toBe(false)
  })
  it('draws nothing without an interval', () => {
    expect(rangePicture({ measure: 'm', aim: 1, observed: 1, interval: null, relation: 'above the aim' })).toBeNull()
    expect(rangePicture({ measure: 'm', aim: 1, observed: 1, interval: [2, 1], relation: 'above the aim' })).toBeNull()
  })
  it('words the comparison and its source', () => {
    const row = parseReading(SOME)!.aim.rows[0]
    expect(aimSentence(row, 'default')).toBe('Out-of-sample Sharpe 0.75 against buy-and-hold 1.55')
    expect(aimSentence(row, 'card')).toBe('Out-of-sample Sharpe 0.75 against the aim 1.55')
    expect(aimSourceLine('default')).toBe('Default aim: beat buy-and-hold')
    expect(aimSourceLine('card')).toBe('Aim from the idea card')
    expect(aimSourceLine('none')).toBe('No aim was recorded for this reading.')
    expect(parseReading(NO_AIM)!.aim.rows).toEqual([])
  })
})

describe('counts', () => {
  it('says each count in plain words and labels a repeat', () => {
    const counts = parseReading(SOME)!.counts
    expect(countLines(counts, [])).toEqual(['Ledger entry 3', 'Family counted as 6 tries', 'Best of 6 variants'])
    expect(countLines(counts, ['repeat'])).toContain('A repeat of an earlier test; it still counts as another try')
    expect(countLines({ trial_n: null, family_trials: null, best_of: null, variants_tried: null, family_id: null }, [])).toEqual([])
  })
})
