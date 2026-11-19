import { expect, test } from '@playwright/test'
import { preparePage } from './support/workstationHarness'

test('the rule result opens first and its setup and checks expand independently', async ({ page }) => {
  const runId = 'c'.repeat(16)
  await preparePage(page, { runs: [{ run_id: runId, kind: 'runs', display_name: 'Synthetic rule' }] })
  await page.route(`**/api/runs/${runId}`, route => route.fulfill({ json: {
    run_id: runId, kind: 'runs', display_name: 'Synthetic rule', manifest: {}, has_trades: false,
    rule_test: { idea: null, rule_sentence: 'Hold after a new high', symbol: 'TEST', rule_params: {}, labels: [],
      diagnostics: null, diagnostics_reason: 'No diagnostic file.' },
  } }))
  await page.route(`**/api/runs/${runId}/checks`, route => route.fulfill({ json: { run_id: runId, checks: [] } }))
  await page.route(`**/api/runs/${runId}/figures`, route => route.fulfill({ json: { run_id: runId, items: [] } }))
  await page.goto(`/#run=${runId}`)
  const summary = page.getByRole('region', { name: 'Rule test', exact: true })
  await expect(summary.getByRole('heading', { name: /Hold after a new high/ })).toBeVisible()
  for (const period of ['Whole period the rule could trade', 'Scored test periods only']) {
    const row = summary.getByRole('region', { name: period, exact: true })
    await expect(row.getByRole('heading', { name: period })).toBeVisible()
    await expect(row.getByText('Charts: not recorded')).toBeVisible()
  }
  await expect(summary.getByRole('region', { name: 'Checks run on this test' })).toContainText('No checks have been run on this test yet.')
  const setup = summary.locator('details').filter({ has: page.locator('summary', { hasText: 'What was tested' }) })
  const checks = summary.locator('details').filter({ has: page.locator('summary', { hasText: 'Checks on the test itself' }) })
  await expect(setup).toHaveJSProperty('open', false)
  await expect(checks).toHaveJSProperty('open', false)
  await setup.locator('summary').click()
  await expect(setup.getByText('no idea text was saved with this run')).toBeVisible()
  await expect(checks).toHaveJSProperty('open', false)
  await checks.locator('summary').click()
  await expect(checks.getByText('No diagnostic file.')).toBeVisible()
  await expect(page.getByRole('table', { name: 'Summary — what this run recorded' })).toHaveCount(0)
})
