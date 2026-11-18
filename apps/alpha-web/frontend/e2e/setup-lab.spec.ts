import { expect, test } from '@playwright/test'
import { preparePage } from './support/workstationHarness'

// Synthetic API responses check presentation only; no market evidence is used.
const run = { find_id: 'a'.repeat(16), description: 'Synthetic pullback', name: 'Synthetic', recorded_at: '2026-11-01T00:00:00Z', assets: [], labels: ['daily-only'] }
const detail = { run, summary: null, spec: null, candidates: [], price_bars: null,
  price_bars_reason: 'Price bars: not recorded as a setup-run snapshot.', sheets: [], studies: [], trades: [], trial_indices: null,
  limits: ['Daily bars only.'], label_explanations: { 'daily-only': 'Only daily bars were used.' } }

test('Setup Lab is reachable and separates empty, missing and failed records', async ({ page }) => {
  await preparePage(page)
  await page.route('**/api/setup/runs', route => route.fulfill({ json: { items: [run] } }))
  await page.route(`**/api/setup/runs/${run.find_id}`, route => route.fulfill({ json: detail }))
  await page.goto('/#page=research&pane=SetupLabPanel')
  await expect(page.getByRole('heading', { name: 'Setup Lab', exact: true })).toBeVisible()
  await expect(page.getByLabel('Recorded setup run')).toHaveValue(run.find_id)
  await expect(page.getByText('No matches recorded.', { exact: true })).toBeVisible()
  await expect(page.getByText('Study: not recorded', { exact: true })).toBeVisible()
  await expect(page.getByRole('complementary', { name: 'What this cannot tell you' })).toContainText('Daily bars only.')
  await page.route('**/api/setup/runs', route => route.fulfill({ json: { items: [] } }))
  await page.reload()
  await expect(page.getByText('No setup runs.', { exact: false })).toBeVisible()
  await page.route('**/api/setup/runs', route => route.fulfill({ status: 422, json: { detail: 'Stored records are corrupt' } }))
  await page.reload()
  await expect(page.getByRole('alert')).toBeVisible()
  await expect(page.getByText('No setup runs.', { exact: false })).toHaveCount(0)
})

test('switching setup runs removes the previous result before the next response', async ({ page }) => {
  await preparePage(page)
  const second = { ...run, find_id: 'b'.repeat(16), description: 'Another synthetic setup' }
  let release!: () => void
  const pending = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/setup/runs', route => route.fulfill({ json: { items: [run, second] } }))
  await page.route(`**/api/setup/runs/${run.find_id}`, route => route.fulfill({ json: detail }))
  await page.route(`**/api/setup/runs/${second.find_id}`, async route => {
    await pending
    await route.fulfill({ json: { ...detail, run: second, price_bars_reason: 'Second setup snapshot: not recorded.' } })
  })
  await page.goto('/#page=research&pane=SetupLabPanel')
  await expect(page.getByRole('heading', { name: 'Synthetic pullback', exact: true })).toBeVisible()
  await page.getByLabel('Recorded setup run').selectOption(second.find_id)
  await expect(page.getByText('Loading selected setup…')).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Synthetic pullback', exact: true })).toHaveCount(0)
  release()
  await expect(page.getByRole('heading', { name: 'Another synthetic setup', exact: true })).toBeVisible()
})
