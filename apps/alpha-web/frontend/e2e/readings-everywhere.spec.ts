import { readFileSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'
import { SOME } from '../src/panels/__fixtures__/readings'
import { BANNED } from '../src/panels/__fixtures__/scanWords'
import { preparePage } from './support/workstationHarness'

// Synthetic API responses check presentation only; no market evidence is used. The manifest is the unit-test fixture
// (a stored gauntlet run), shown old style (letter only) and new style (with a stored reading).
const manifestFile = new URL('../src/explain/__fixtures__/validate-b.json', import.meta.url)
const validate = JSON.parse(readFileSync(manifestFile, 'utf8')) as Record<string, unknown>
const runId = 'e'.repeat(16)
const ALLOWED = /the level used by the old grade|old grade|graded [A-Z]+ under the old rules/gi
const LETTER = /(?<![\w'./-])[A-F](?![\w'./-])/
const ARTICLE = /(?:^|(?<=[.!?:] ))A(?= [A-Za-z])/gm
const THEMES = ['light', 'dim', 'dark'] as const

function assertOwnerText(text: string): void {
  const shown = text.replace(ALLOWED, '')
  expect(shown.match(BANNED)?.[0]).toBeUndefined()
  expect(shown.replace(ARTICLE, '').match(LETTER)?.[0]).toBeUndefined()
}

const listed = (id: string, over: Record<string, unknown>) => ({
  run_id: id, kind: 'runs', command: 'validate', label: 'SYN · ma_cross', display_name: `Synthetic ${id.slice(0, 4)}`, market: 'unknown',
  symbol: 'SPY', mtime: 1_700_000_000, passed: false, verdict: 'C', evidence: null, run_context_kind: 'standalone_sandbox', run_context_project_id: null,
  run_context_watermark: 'STANDALONE_UNQUALIFIED', research_gate_watermark: null, rule_test_labels: null, symbols: null, snapshot_id: null, snapshot_hash: null, ...over,
})

async function openRun(page: Page, manifest: Record<string, unknown>): Promise<void> {
  await preparePage(page, { runs: [listed(runId, { evidence: manifest.reading ? 'some evidence' : null })] })
  await page.route(`**/api/runs/${runId}`, route => route.fulfill({ json: {
    run_id: runId, kind: 'runs', display_name: 'Synthetic validate', manifest, has_trades: false, rule_test: null,
  } }))
  await page.route(`**/api/runs/${runId}/figures`, route => route.fulfill({ json: { run_id: runId, items: [] } }))
  // The Gates charts read these two; an old run has neither.
  await page.route(`**/api/runs/${runId}/nulls`, route => route.fulfill({ status: 404, json: { detail: 'no null distributions for this run' } }))
  await page.route('**/api/candles/**', route => route.fulfill({ status: 404, json: { detail: 'no bars' } }))
  await page.route('**/api/risk/scenario**', route => route.fulfill({ json: {
    run_id: runId, confidence: 0.95, provenance: { metric_basis: null }, scenarios: [
      { name: 'baseline', sharpe: 0.62, annual_vol: 0.14, max_drawdown: -0.18, value_at_risk: -0.012, expected_shortfall: -0.018, total_return: 0.42 },
      { name: 'vol x1.5', sharpe: 0.6, annual_vol: 0.21, max_drawdown: -0.27, value_at_risk: -0.018, expected_shortfall: -0.027, total_return: 0.55 },
    ],
  } }))
  await page.goto(`/#run=${runId}`)
}

async function leafText(page: Page, leaf: string): Promise<string> {
  await page.getByRole('button', { name: leaf, exact: true }).click()
  const region = page.getByRole('region', { name: 'Report analytical content' })
  await expect(region).toBeVisible()
  return region.innerText()
}

for (const [style, manifest] of [['an old run (letter only)', validate], ['a new run (with a stored reading)', { ...validate, reading: SOME }]] as const) {
  for (const theme of THEMES) {
    test(`the Gates, Stress test and Summary tabs of ${style} say no grade or pass word in the ${theme} theme`, async ({ page }) => {
      await openRun(page, manifest)
      await page.getByRole('combobox', { name: 'Theme', exact: true }).selectOption(theme)
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme)
      const summary = await page.getByRole('region', { name: 'Report analytical content' }).innerText()
      expect(summary).not.toMatch(/\bPassed\b/)
      assertOwnerText(summary)
      const gates = await leafText(page, 'Gates')
      expect(gates).toMatch(/the five checks behind the reading/i)
      expect(gates).toContain('computed')
      expect(gates).toContain('How this check works')
      expect(gates).toMatch(/The level used by the old grade/)
      assertOwnerText(gates)
      assertOwnerText(await leafText(page, 'Stress test'))
      await expect(page.locator('.explain-card.tone-good, .explain-card.tone-bad')).toHaveCount(0)
    })
  }
}

test('a gate card never takes a good or bad colour and keeps its fact check as an icon and a word', async ({ page }) => {
  await openRun(page, validate)
  await page.getByRole('button', { name: 'Gates', exact: true }).click()
  const cards = page.locator('.explain-card')
  await expect(cards).toHaveCount(5)
  const colours = await cards.evaluateAll(nodes => nodes.map(node => getComputedStyle(node).borderLeftColor))
  expect(new Set(colours).size).toBe(1)
  const state = cards.first().locator('.explain-state')
  await expect(state).toHaveText('computed')
  await expect(state.locator('svg')).toBeVisible()
})

for (const theme of THEMES) {
  test(`the Pipeline shows an evidence word or a muted old-rules line, never a chip, in the ${theme} theme`, async ({ page }) => {
    await preparePage(page, { runs: [
      listed('a'.repeat(16), { command: 'validate', evidence: 'some evidence', verdict: 'B', passed: true }),
      listed('b'.repeat(16), { command: 'backtest_run', evidence: null, verdict: 'C', passed: false }),
    ], initialSymbol: null })
    await page.goto('/#page=strategies&pane=Pipeline')
    await page.getByRole('combobox', { name: 'Theme', exact: true }).selectOption(theme)
    const stages = page.locator('.pipeline')
    await expect(stages).toContainText('some evidence')
    await expect(stages).toContainText('graded C under the old rules')
    await expect(stages).toContainText('The gauntlet: five checks, read in context')
    await expect(page.locator('.pipeline .chip.pass, .pipeline .chip.fail, .pipeline .verdict')).toHaveCount(0)
    assertOwnerText(await stages.innerText())
  })
}

for (const theme of THEMES) {
  test(`the activity feed and the toast show the evidence word, not a verdict or a gate result, in the ${theme} theme`, async ({ page }) => {
    await preparePage(page)
    await page.goto('/#page=operations&pane=ActivityFeed')
    await page.getByRole('combobox', { name: 'Theme', exact: true }).selectOption(theme)
    const send = (run: Record<string, unknown>) => page.evaluate(data => {
      const stream = (window as unknown as { __alphaStream: EventTarget }).__alphaStream
      stream.dispatchEvent(new MessageEvent('run_added', { data: JSON.stringify(data) }))
    }, run)
    await send(listed('c'.repeat(16), { evidence: 'not clear of chance', verdict: 'D', passed: false }))
    await send(listed('d'.repeat(16), { evidence: null, verdict: 'A', passed: true }))
    const feed = page.locator('.feed')
    await expect(feed).toContainText('not clear of chance')
    await expect(feed).toContainText('graded A under the old rules')
    assertOwnerText(await feed.innerText())
    const toasts = page.locator('.toasts')
    await expect(toasts).toContainText('SYN · ma_cross — not clear of chance')
    await expect(page.locator('.toast.tone-good, .toast.tone-bad')).toHaveCount(0)
    assertOwnerText((await toasts.innerText()).replace(/\bopen\b|✕/g, ''))
  })
}

test('the command palette lists a run with its evidence word', async ({ page }) => {
  await preparePage(page, { runs: [listed('f'.repeat(16), { evidence: 'some evidence', verdict: 'B', passed: true }),
    listed('0'.repeat(15) + '1', { evidence: null, verdict: 'C', passed: false })] })
  await page.goto('/#legacy')
  await expect(page.getByRole('combobox', { name: 'Theme', exact: true })).toBeVisible()
  await page.keyboard.press('Control+K')
  await page.getByRole('option', { name: /Open run/ }).click()
  const list = page.getByRole('listbox')
  await expect(list).toContainText('runs · SYN · ma_cross · some evidence')
  await expect(list).toContainText('runs · SYN · ma_cross · graded C under the old rules')
  assertOwnerText(await list.innerText())
})
