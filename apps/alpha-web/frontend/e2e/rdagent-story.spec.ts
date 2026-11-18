import { expect, test } from '@playwright/test'
import type { components } from '../src/api/generated'
import { openTask, preparePage } from './support/workstationHarness'

type Schema = components['schemas']
const fact = (value: Schema['RecordedFact']['value'] = null): Schema['RecordedFact'] => ({ value })
const run: Schema['RdAgentRun'] = {
  run_id: 'synthetic-story', folder: 'Synthetic story fixture', started_at: fact(), ended_at: fact(),
  outcome: fact('completed'), rounds_completed: fact(), counted_calls: fact(), local_embedding_calls: fact(),
  provider_embedding_calls: fact(), cost_usd: fact(), factors_proposed: fact(), stages: {},
  universe_size: fact(), universe_includes_delisted: fact(),
}
const idea: Schema['RdAgentIdea'] = {
  id: 'synthetic-refusal', round: fact(0), round_kind: 'loop', name: fact('Synthetic proposal'),
  description: fact(), direction: fact(), clock: fact(), reason: fact(),
  system_statuses: ['refused_missing_declaration'], refusal: fact('The direction was missing.'),
  feedback: fact(), feedback_scope: 'unknown', trial: null,
  stages: { proposed: true, refused: true, coded: false, ran: false, judged: false, shortlisted: false, candidate: false },
  labels: [], code_file: fact(), raw: '{"synthetic_raw_marker":true}',
}
const detail: Schema['RdAgentDetail'] = {
  run, funnel: {}, factors: [], refusals: [], timing: [], caps: {}, months: {}, cache: {}, providers: {},
  universe: {}, identity_splits: [], identity_rescales: [], notes: [],
  story: { ideas: [idea], journey: Object.fromEntries(Object.entries(idea.stages).map(([stage, value]) => [stage, fact(value ? 1 : 0)])),
    missing_links: [], ending: 'finished', ending_reason: fact('completed'), minutes: fact() },
}

test('story links reveal counted ideas without replacing the workstation URL', async ({ page }) => {
  await preparePage(page, { extraGet: {
    '/api/rdagent/runs': { items: [run] }, '/api/rdagent/runs/synthetic-story': detail,
  } })
  await openTask(page, 'Research', 'RD-Agent')
  await expect(page.getByRole('heading', { name: 'What happened in this run' })).toBeVisible()
  const originalURL = page.url()
  await page.locator('a[href="#journey-refused"]').click()
  await expect(page.locator('#journey-refused')).toHaveAttribute('open', '')
  await page.locator('#journey-refused').getByRole('link', { name: 'Synthetic proposal' }).click()
  const card = page.locator('#idea-synthetic-refusal')
  await expect(card).toBeFocused()
  await expect(card.getByText('The direction was missing.', { exact: false })).toBeVisible()
  await expect(card.getByText('synthetic_raw_marker', { exact: false })).not.toBeVisible()
  await card.getByText('technical detail', { exact: true }).click()
  await expect(card.getByText('synthetic_raw_marker', { exact: false })).toBeVisible()
  await expect(page).toHaveURL(originalURL)
  await expect(page.getByText('no ideas were judged', { exact: false })).toBeVisible()
})
