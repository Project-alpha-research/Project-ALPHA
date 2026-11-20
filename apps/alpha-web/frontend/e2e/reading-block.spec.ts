import { expect, test, type Page } from '@playwright/test'
import { FAULT, SOME } from '../src/panels/__fixtures__/readings'
import { preparePage } from './support/workstationHarness'

// Synthetic API responses check presentation only; no market evidence is used.
const runId = 'd'.repeat(16)
const stored = { tool: 'market.vol_regimes', outcome: 'ok', reading: 'Calm months made 90% of the return.', error: null,
  labels: ['declared'], recorded_at: '2026-11-19T10:00:00+00:00', status: 'declared' }

async function openReport(page: Page, reading: Record<string, unknown> | null, manifest: Record<string, unknown> = {}): Promise<void> {
  await preparePage(page, { runs: [{ run_id: runId, kind: 'runs', display_name: 'Synthetic rule' }] })
  await page.route(`**/api/runs/${runId}`, route => route.fulfill({ json: {
    run_id: runId, kind: 'runs', display_name: 'Synthetic rule', manifest, has_trades: false,
    rule_test: { idea: null, rule_sentence: 'Hold after a new high', symbol: 'TEST', rule_params: {}, labels: ['exploratory'],
      diagnostics: null, diagnostics_reason: 'No diagnostic file.' },
  } }))
  await page.route(`**/api/runs/${runId}/checks`, route => route.fulfill({ json: {
    run_id: runId, checks: [stored], reading,
    counts: { total: 1, declared: 1, exploratory: 0, text: '1 check run on this result: 1 declared, 0 exploratory' },
  } }))
  await page.route(`**/api/runs/${runId}/figures`, route => route.fulfill({ json: { run_id: runId, items: [] } }))
  await page.goto(`/#run=${runId}`)
}

test('the report shows a reading with its checks, scale, aim picture and counts, and no grade', async ({ page }) => {
  await openReport(page, SOME)
  const block = page.getByRole('region', { name: 'Reading', exact: true })
  await expect(block.getByRole('list', { name: 'Fact checks' })).toContainText('sound')
  await expect(block.getByText('Out-of-sample Sharpe 0.75; buy-and-hold over the same days 1.55.')).toBeVisible()
  await expect(block.getByRole('heading', { name: 'Evidence strength: some evidence' })).toBeVisible()
  await expect(block.locator('[aria-current="step"]')).toHaveText('some evidence')
  await expect(block.getByRole('list', { name: 'Evidence strength scale, four steps' }).getByRole('listitem')).toHaveCount(4)
  await expect(block.getByText('Out-of-sample Sharpe 0.75 against buy-and-hold 1.55')).toBeVisible()
  await expect(block.getByText('below the aim', { exact: true })).toBeVisible()
  await expect(block.getByRole('img', { name: /95% range 0\.10 to 1\.40; the aim 1\.55 is outside this range/ })).toBeVisible()
  await expect(block.getByRole('table', { name: 'Measures' }).or(block.getByRole('region', { name: 'Measures' }))).toBeVisible()
  await expect(block.getByText('Ledger entry 3')).toBeVisible()
  await expect(block.getByText('A reading describes the evidence. It is not advice and not an approval.')).toBeVisible()
  const report = page.getByRole('region', { name: 'Rule test', exact: true })
  await expect(report.getByText('1 check run on this result: 1 declared, 0 exploratory')).toBeVisible()
  await expect(report.locator('.rule-test-status-chip')).toHaveText('declared')
  await expect(report).not.toContainText(/\b(supported|rejected|inconclusive|verdict)\b/i)
})

test('a fault replaces the reading and keeps its numbers behind a closed disclosure', async ({ page }) => {
  await openReport(page, FAULT)
  const block = page.getByRole('alert').filter({ hasText: 'Fix this first. No reading.' })
  await expect(block).toContainText('Fault: a fill came at or before its decision (look-ahead). Fix this first. No reading.')
  await expect(block.getByText('Against the aim')).toHaveCount(0)
  const numbers = block.locator('details')
  await expect(numbers).toHaveJSProperty('open', false)
  await expect(numbers.getByText('out-of-sample Sharpe: 3.40')).toBeHidden()
  await numbers.locator('summary').focus()
  await page.keyboard.press('Enter')
  await expect(numbers.getByText('out-of-sample Sharpe: 3.40')).toBeVisible()
})

test('an old run with a letter and no reading says so in muted text', async ({ page }) => {
  await openReport(page, null, { verdict: { overall: 'C' } })
  const block = page.getByRole('region', { name: 'Reading', exact: true })
  await expect(block).toContainText('graded C under the old rules')
  await expect(block.getByText('Evidence strength')).toHaveCount(0)
})
