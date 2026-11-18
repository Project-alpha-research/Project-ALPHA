import type { components } from '../api/generated'
import { formatDuration } from '../util/formatTime'

type Schema = components['schemas']
export type Idea = Schema['RdAgentIdea']
export type Story = Schema['RdAgentStory']
type Fact = Schema['RecordedFact']
type Factor = Schema['RdAgentFactor']

export const notice = 'Exploratory results. Nothing here is evidence of an edge until a candidate is confirmed on reserved data.'
export const stages = {
  proposed: 'Proposed', refused: 'Refused before coding', coded: 'Coded', ran: 'Ran',
  judged: 'Judged', shortlisted: 'Shortlisted — not a pass', candidate: 'Candidate',
} as const

const statuses: Record<string, string> = {
  DIAGNOSTIC: 'This was an extra comparison; it cannot pass or become evidence.',
  refused_missing_declaration: 'The proposal was refused before coding because its direction, holding clock or economic reason was missing.',
  refused_closed_family: 'This kind of idea was already closed after earlier failures, so the proposal was refused before coding.',
  no_admissible_idea: 'Repeated refusals ended this round before coding.',
  proposal_failed_provider_timeout: 'The model provider timed out before a proposal was recorded.',
  proposal_failed_provider_error: 'The model provider failed before a proposal was recorded.',
  coding_failed_provider_timeout: 'The model provider timed out during this round; no new test result was invented.',
  coding_failed_provider_error: 'The model provider failed during this round; no new test result was invented.',
  coding_failed_internal_error: 'An internal coding error ended this round; completed ideas could still be judged.',
  critic_unavailable_provider_timeout: 'The code critic timed out; execution and value checks remained in force.',
  critic_unavailable_provider_error: 'The code critic was unavailable because its provider failed; execution and value checks remained in force.',
  abandoned_at_cap: 'A budget stopped this unfinished round before it created a trial.',
  abandoned_after_error: 'An error stopped this unfinished round before it created a trial.',
  NOT_RUN: 'This check was not run.', OK: 'This stage produced usable values.',
  PASS: 'This recorded check passed; it does not establish an edge.', FAIL: 'This recorded check failed.',
  FAILED: 'The code produced no usable values; the specific reason was not recorded.',
  critic_rejected: 'The code ran, but the code critic did not accept it.',
  cap_reached: 'The call budget stopped coding before usable values were produced.',
  exception: 'The code failed with an exception and produced no usable values.',
  bad_output: 'The code file was absent or did not produce the required numeric values.',
  LOOKAHEAD: 'The idea changed when future data was removed, so this result cannot be trusted.',
  UNSTABLE: 'The idea changed on identical inputs, so its result is not reproducible.',
  DEGENERATE: 'There were too few usable observations or too little variation to judge this idea.',
  ERROR: 'The evaluation failed, so there is no usable verdict from that check.',
  SCREEN_FAIL: 'The ranking test did not find enough evidence to keep this idea.',
  SPREAD_FAIL: 'The highest-ranked group did not beat the lowest-ranked group before costs.',
  REPLAY_FAIL: 'The trading replay did not retain positive excess returns after costs.',
  DEFLATION_FAIL: 'The idea passed the earlier checks but failed the correction for trying many ideas.',
  CANDIDATE: 'The recorded checks passed; this is a lead for an owner-approved reserved-data check, not evidence of an edge.',
  FAST_ONLY: 'Only the daily holding clock passed, so this is not a swing candidate.',
  REPEAT: 'This repeats an earlier evaluated idea and supplies no new evidence.',
  IMPORTED: 'This is a historical trial, not a new test by this run.',
  coded: 'The system produced code for this idea.',
}
const labels: Record<string, string> = {
  'exploratory, not admitted, not yet confirmed': 'This is exploratory work; it has not been admitted as evidence or confirmed on reserved data.',
  shortlist: 'Shortlisted means the primary screen, spread and replay passed; shortlisted is not a pass and is not evidence of profit.',
  'perp-funding': 'This idea uses perpetual-futures funding inputs and ranks only names with recorded funding coverage; the tested returns are spot returns.',
  composite_suspect: 'This idea resembles a blend of earlier tries; that warning is a diagnostic, not a new verdict.',
  'diagnostic clocks': 'Other holding clocks and the opposite direction are extra comparisons only; they cannot pass.',
}
const endings: Record<string, string> = {
  finished: 'The run finished.', budget: 'The run stopped at a call, money or time budget.',
  provider: 'The run stopped because the model provider failed.',
  internal_error: 'The run stopped because of an internal coding error.',
  error: 'The run stopped with an error; a more specific ending is not recorded.',
  not_recorded: 'How the run ended is not recorded.',
}
function sentence(table: Record<string, string>, key: string): string {
  if (!Object.hasOwn(table, key)) throw new Error(`Unexplained RD-Agent value: ${key}`)
  return table[key]
}
export const statusSentence = (status: string): string => sentence(statuses, status)
export const labelSentence = (label: string): string => sentence(labels, label)
export const endingSentence = (ending: string): string => sentence(endings, ending)
export function runOutcome(value: Fact['value']): string {
  if (value === null) return endingSentence('not_recorded')
  return sentence({ completed: endings.finished, error: endings.error, 'stopped by a cap': endings.budget }, String(value))
}
export function recorded(fact: Fact | undefined | null): string {
  if (fact?.value === null || fact?.value === undefined) return 'not recorded'
  return Array.isArray(fact.value) ? fact.value.join(', ') : String(fact.value)
}
export function directionSentence(value: Fact['value']): string {
  if (value === null) return 'Direction: not recorded.'
  if (value === 1) return 'The proposer intended to buy high-ranked names.'
  if (value === -1) return 'The proposer intended to buy low-ranked names.'
  throw new Error('Unexplained RD-Agent direction')
}
export function clockSentence(value: Fact['value']): string {
  if (value === null) return 'Holding clock: not recorded.'
  return sentence({ daily: 'The holding clock is one day.', weekly: 'The holding clock is seven days.', monthly: 'The holding clock is 28 days.' }, String(value))
}
export const glossary: Record<string, string> = {
  Idea: 'A proposed rule for ranking which instruments to hold.',
  Screen: 'The first test asks whether the ranking predicts later returns.',
  Spread: 'The gap between the returns of the highest- and lowest-ranked groups before trading costs.',
  Replay: 'A simulation of the recorded trading rule with costs included.',
  'Many-tries correction': 'A check that makes finding a lucky winner harder when many ideas have been tried.',
  Shortlist: 'An idea that cleared the first checks, but being shortlisted is not a pass.',
  Candidate: 'An idea that cleared the recorded checks and still needs owner-approved confirmation.',
  Family: 'A group of ideas based on the same underlying mechanism.',
  Clock: 'How long the proposal intends to hold a position before rebalancing.',
  'Look-ahead check': 'A check that removing future data does not change earlier values.',
  Diagnostic: 'An extra comparison that cannot grant a pass.',
  'Reserved data': 'Data kept aside for a later confirmation that only the owner can approve.',
}

export interface StoryPart { text: string; target?: string }
export function storySummary(story: Story | null, run: Schema['RdAgentRun'] | null): StoryPart[][] {
  const count = (stage: keyof typeof stages): StoryPart => ({ text: recorded(story?.journey[stage]), target: `journey-${stage}` })
  const text = (value: string): StoryPart => ({ text: value })
  const refused = [...new Set(story?.ideas.filter(idea => idea.stages.refused).flatMap(idea => idea.system_statuses) ?? [])]
  const clause = (status: string): string => statusSentence(status).replace(/\.$/, '')
  const reason = refused.map(clause).join('; ')
  const noJudging = story?.journey.judged?.value === 0
    ? '; no ideas were judged — ' + ([...new Set([...(story.events ?? []), ...story.ideas.flatMap(idea => idea.system_statuses)])].map(clause).join('; ') || 'the reason is not recorded')
    : ''
  return [
    [text('Ideas proposed: '), count('proposed'), text('.')],
    [count('refused'), text(` ideas were refused before coding${reason ? `: ${reason}` : story?.journey.refused?.value === 0 ? '' : '; the refusal reasons are not recorded'}.`)],
    [count('coded'), text(' ideas were coded, '), count('ran'), text(' ran, and '), count('judged'), text(` were judged${noJudging}.`)],
    [count('shortlisted'), text(' ideas were shortlisted (not a pass), and '), count('candidate'), text(' became candidates for an owner-approved confirmation, not evidence of an edge.')],
    [text('The recorded cost was '), { text: `${recorded(run?.cost_usd)} USD`, target: 'run-record' }, text(' and elapsed time was '),
      { text: typeof story?.minutes.value === 'number' ? formatDuration(story.minutes.value) : 'not recorded', target: 'run-record' }, text('.')],
    [text(endingSentence(story?.ending ?? 'not_recorded'))],
  ]
}

export interface StoryNumber { label: string; value: string; gloss: string }
export function verdictNumbers(factor: Factor | null): StoryNumber[] {
  if (!factor) return []
  const clockName = factor.figures.primary_clock?.value ?? factor.figures.lead_clock?.value
  if (typeof clockName !== 'string') return []
  const clock = factor.clocks[clockName]
  if (!clock) return []
  const number = (label: string, fact: Fact | undefined, gloss: string): StoryNumber => ({ label, value: recorded(fact), gloss })
  const cutoff = recorded(clock.figures.screen_cutoff?.value == null ? factor.figures.screen_cutoff : clock.figures.screen_cutoff)
  const passLine = factor.figures.screen_rule?.value === 'alpha-investing-simple-1'
    ? `the pass line is half the recorded cutoff ${cutoff}`
    : `the recorded cutoff is ${cutoff}; the pass-line convention is not recorded`
  const screen = number('Noise-test probability', clock.figures.p,
    `Under no predictive relationship, the chance of a result this strong; ${passLine}.`)
  const deflation = number('Many-tries confidence', clock.deflation.dsr,
    `Recorded confidence after allowing for repeated tries; the pass line was ${recorded(clock.deflation.threshold)}.`)
  const excess = number('Annual excess return after costs', clock.replay.net_annual_excess,
    'The replay’s yearly return above its benchmark after trading costs; a fraction, not a promise.')
  if (factor.status === 'SPREAD_FAIL') return [
    number('Highest group return', clock.spread.top_third_mean_return, 'Average return per holding period before costs.'),
    number('Lowest group return', clock.spread.bottom_third_mean_return, 'The comparison group’s average return before costs.'),
    number('Gap between groups', clock.spread.mean_spread, 'The highest group must beat the lowest before costs.'),
  ]
  if (factor.status === 'SCREEN_FAIL') return [screen,
    number('Effective observations', clock.screen.effective_n, 'The stored observation count after allowing for dependence.')]
  if (factor.status === 'DEFLATION_FAIL') return [deflation,
    number('Tries counted', clock.deflation.n_trials, 'How many tries the stored many-tries check allowed for.')]
  if (clock.replay.counted_only?.value != null) return [screen, deflation]
  if (factor.status === 'CANDIDATE') return [screen, excess, deflation]
  if (factor.status === 'REPLAY_FAIL') return [excess,
    number('Annual excess return before costs', clock.replay.gross_annual_excess, 'The same replay before fees and slippage.')]
  return []
}

export function roundHeading(idea: Idea): string {
  if (idea.round.value === null || idea.round_kind === 'unknown') return 'Round: not recorded'
  return idea.round_kind === 'evaluation'
    ? `Evaluation round ${recorded(idea.round)} — loop round link not recorded`
    : `Loop round ${recorded(idea.round)} — evaluation link not recorded`
}
export function systemStory(idea: Idea): string {
  return idea.system_statuses.length ? idea.system_statuses.map(statusSentence).join(' ') : 'What the system did: not recorded.'
}
export function testStory(idea: Idea): string {
  return idea.trial ? statusSentence(idea.trial.status) : 'The test verdict is not recorded for this idea.'
}
