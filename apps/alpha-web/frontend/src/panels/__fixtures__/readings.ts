// Synthetic readings in the shape the command line stores (`AlphaReadingV1`); no real data.

const BASIS = 'walk-forward out-of-sample, after costs'

const SOUND_CHECKS = [
  { name: 'numbers', state: 'sound', detail: 'every statistic was computed' },
  { name: 'no-look-ahead', state: 'sound', detail: 'every fill came after its decision' },
  { name: 'data-health', state: 'not-checked', detail: 'the data health was not checked' },
]

const measures = (sharpe: number, interval: [number, number] | null) => [
  { name: 'out-of-sample Sharpe', value: sharpe, interval_95: interval, basis: BASIS },
  { name: 'deflated Sharpe', value: 0.99, interval_95: null, basis: BASIS },
  { name: 'closed trades', value: 52, interval_95: null, basis: BASIS },
]

const aimRow = (observed: number, aim: number, interval: [number, number], relation: string) => (
  { measure: 'out-of-sample Sharpe', aim, observed, interval_95: interval, relation }
)

const counts = { trial_n: 3, family_id: 'spine:ma_cross', family_trials: 6, variants_tried: 5, best_of: 6 }

export function reading(word: string | null, over: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    schema: 'AlphaReadingV1',
    checks: SOUND_CHECKS,
    measures: measures(0.75, [0.1, 1.4]),
    evidence: { word, because: ['Random-data tests held: 3 of 3.', 'Sharpe interval 0.10 to 1.40 (95%).'] },
    aim: { source: 'default', basis: 'buy-and-hold Sharpe over the same scored days, no costs',
      rows: [aimRow(0.75, 1.55, [0.1, 1.4], 'below the aim')] },
    counts,
    sentence: 'Out-of-sample Sharpe 0.75; buy-and-hold over the same days 1.55. Default aim: beat buy-and-hold; this reading is below the aim. Evidence strength: some evidence.',
    ...over,
  }
}

export const SOME = reading('some evidence')
export const CLEAR = reading('clear of chance', {
  aim: { source: 'card', basis: null, rows: [aimRow(1.6, 0.9, [1.1, 2.1], 'above the aim')] },
})
export const NOT_CLEAR = reading('not clear of chance')
export const TOO_LITTLE = reading('too little to read')
export const NO_AIM = reading('some evidence', { aim: { source: 'none', basis: null, rows: [] } })
export const WITHIN = reading('some evidence', {
  aim: { source: 'default', basis: null, rows: [aimRow(0.75, 0.9, [0.1, 1.4], 'within the uncertainty of the aim')] },
})
export const FAULT = reading(null, {
  checks: [
    { name: 'numbers', state: 'sound', detail: 'every statistic was computed' },
    { name: 'no-look-ahead', state: 'fault', detail: 'a fill came at or before its decision (look-ahead)' },
    { name: 'data-health', state: 'not-checked', detail: 'the data health was not checked' },
  ],
  evidence: { word: null, because: [] },
  aim: { source: 'default', basis: null, rows: [] },
  measures: measures(3.4, null).map(row => ({ ...row, not_to_be_read: true })),
  sentence: 'Fault: a fill came at or before its decision (look-ahead). Fix this first. No reading.',
})
