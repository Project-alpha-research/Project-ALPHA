import { expect, test } from '@playwright/test'
import type { components } from '../src/api/generated'
import { openTask, preparePage } from './support/workstationHarness'

type Schema = components['schemas']
const fact: Schema['RecordedFact'] = { value: null }
const run: Schema['RdAgentRun'] = {
  run_id: 'example', folder: 'Synthetic run', started_at: fact, ended_at: fact,
  outcome: fact, rounds_completed: fact, counted_calls: fact, local_embedding_calls: fact,
  provider_embedding_calls: fact, cost_usd: fact, factors_proposed: fact, stages: {},
  universe_size: fact, universe_includes_delisted: fact,
}
const detail: Schema['RdAgentDetail'] = {
  run, funnel: {}, factors: [], refusals: [], timing: [], caps: {}, months: {}, cache: {}, providers: {},
  universe: {}, identity_splits: [], identity_rescales: [], notes: [],
  journeys: [
    { id: 'built', name: 'Synthetic idea', iteration: 1, verdict: 'SCREEN_FAIL', built: true },
    { id: 'missing', name: 'Second idea', iteration: 2, verdict: null, built: false },
  ],
}
const story: Schema['StoredJourney'] = {
  iteration: 1, name: 'Synthetic idea', code_sha256: 'a'.repeat(64),
  steps: ['Idea', 'Calculation', 'Leak check', 'Quick test', 'Trading test', 'Feedback', 'Limits']
    .map((title, i) => ({ title, source: ['evaluations.jsonl'], own_words: i === 0 ? 'Synthetic wording.' : null,
      facts: i === 6 ? ['Stored exploratory label.'] : [] })),
}

test('select an idea and disclose its stored words and sources in place', async ({ page }) => {
  const base = '/api/rdagent/runs/example'
  const command = 'uv run alpha ledger journey --run-dir runs/example --factor second'
  await preparePage(page, { extraGet: {
    '/api/rdagent/runs': { items: [run] }, [base]: detail,
    [base + '/journeys/built']: story, [base + '/journeys/missing']: { reason: 'Journey not built yet', command },
  } })
  await openTask(page, 'Research', 'RD-Agent')
  const url = page.url()
  await expect(page.getByRole('heading', { name: '7. Limits' })).toBeVisible()
  await expect(page.getByText('Stored exploratory label.')).toBeVisible()
  const first = page.locator('section.journey-step').first()
  await expect(first.getByText('Synthetic wording.')).toBeHidden()
  await first.getByText("Show the agent's own words").click()
  await expect(first.getByText('Synthetic wording.')).toBeVisible()
  await expect(first.getByText('evaluations.jsonl')).toBeHidden()
  await first.getByText('Where this comes from').click()
  await expect(first.getByText('evaluations.jsonl')).toBeVisible()
  await page.getByRole('combobox', { name: 'Idea', exact: true }).selectOption('missing')
  await expect(page.getByText(command, { exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: '1. Idea' })).toHaveCount(0)
  await expect(page).toHaveURL(url)
})
