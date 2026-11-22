import { readFileSync } from 'node:fs'
import { expect, test } from '@playwright/test'
import { preparePage } from './support/workstationHarness'

// A synthetic owner-rule run: the screens must state the rule in words, with its family and labels.
const manifest = JSON.parse(readFileSync(new URL('../src/explain/__fixtures__/validate-b.json', import.meta.url), 'utf8')) as Record<string, unknown>
const runId = 'e'.repeat(16)
const SENTENCE = 'Buy at the next open when the 14-day RSI is below 30 and the close is above the 200-day average. '
  + 'Sell at the next open when that stops being true. Long or flat.'
const shots = process.env.OWNER_RULE_SHOTS

test('the report and Gates screens state an owner rule in words, with its family and labels', async ({ page }) => {
  const problems: string[] = []
  page.on('pageerror', error => problems.push(error.message))
  // The three 404 resource loads are this fixture's own missing series, nulls and prices: the app shows a plain note for each.
  page.on('console', message => {
    if (message.type() === 'error' && !message.text().startsWith('Failed to load resource: the server responded with a status of 404')) problems.push(message.text())
  })
  await preparePage(page, { runs: [{ run_id: runId, kind: 'runs', command: 'validate', display_name: 'Synthetic owner rule', symbol: 'TEST', mtime: 1_700_000_000 }] })
  await page.route(`**/api/runs/${runId}`, route => route.fulfill({ json: {
    run_id: runId, kind: 'runs', display_name: 'Synthetic owner rule', manifest, has_trades: false,
    rule_test: { idea: null, name: 'owner-rsi-dip', rule_kind: 'owner', rule_params: {}, rule_sentence: SENTENCE,
      rule_family: 'owner:0123456789ab', symbol: 'TEST', labels: ['null-closes-for-high-low'],
      diagnostics: null, diagnostics_reason: 'No diagnostic file.' },
  } }))
  await page.route(`**/api/runs/${runId}/checks`, route => route.fulfill({ json: { run_id: runId, checks: [] } }))
  await page.route(`**/api/runs/${runId}/figures`, route => route.fulfill({ json: { run_id: runId, items: [] } }))
  await page.route(`**/api/runs/${runId}/series**`, route => route.fulfill({ status: 404, json: { detail: 'no series' } }))
  await page.route(`**/api/runs/${runId}/nulls`, route => route.fulfill({ status: 404, json: { detail: 'none' } }))
  await page.route('**/api/candles/TEST**', route => route.fulfill({ json: { symbol: 'TEST', snapshot_id: null, provenance: {}, bars: [] } }))
  await page.goto(`/#run=${runId}`)
  const words = page.getByRole('region', { name: 'The rule in words' })
  await expect(words).toContainText(SENTENCE)
  await expect(words).toContainText('owner:0123456789ab')
  await expect(words).toContainText('null-closes-for-high-low')
  await expect(words).toContainText('uses closes for high and low')
  if (shots) await page.screenshot({ path: `${shots}/report-owner-rule.png` })
  await page.getByRole('button', { name: 'Gates', exact: true }).click()
  await expect(page.getByRole('region', { name: 'The rule in words' })).toContainText(SENTENCE)
  await expect(page.getByRole('region', { name: 'The rule in words' })).toContainText('owner:0123456789ab')
  if (shots) await page.screenshot({ path: `${shots}/gates-owner-rule.png` })
  expect(problems).toEqual([])
})
