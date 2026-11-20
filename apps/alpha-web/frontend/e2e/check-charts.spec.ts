import { readFileSync } from 'node:fs'
import { expect, test, type Page } from '@playwright/test'
import { BANNED } from '../src/panels/__fixtures__/scanWords'
import { preparePage } from './support/workstationHarness'

// Synthetic API responses check presentation only; no market evidence is used. The manifest is the unit-test fixture
// (a stored gauntlet run) with fold dates added, the way a new run stores them.
const base = JSON.parse(readFileSync(new URL('../src/explain/__fixtures__/validate-b.json', import.meta.url), 'utf8')) as Record<string, any>
const runId = 'c'.repeat(16)
const START = Date.parse('2015-01-02T00:00:00Z')
const DAY = 86_400_000
const iso = (index: number): string => new Date(START + index * DAY).toISOString()

function dated(overlap: boolean): Record<string, unknown> {
  const folds = (base.folds as Record<string, number>[]).map((fold, i) => ({
    ...fold,
    train_start_ts: iso(fold.train_start), train_end_ts: iso(overlap && i === 3 ? fold.test_start + 20 : fold.train_end),
    test_start_ts: iso(fold.test_start), test_end_ts: iso(fold.test_end),
  }))
  return { ...base, folds, oos_semantics: 'fixed_rule_evaluation_no_refit' }
}

type Prices = 'bars' | 'error' | 'empty'

async function openRun(page: Page, manifest: Record<string, unknown>, withData: boolean, prices: Prices = 'bars'): Promise<void> {
  await preparePage(page, { runs: [{ run_id: runId, kind: 'runs', command: 'validate', display_name: 'Synthetic validate', symbol: 'AAPL', mtime: 1_700_000_000 }] })
  await page.route(`**/api/runs/${runId}`, route => route.fulfill({ json: { run_id: runId, kind: 'runs', display_name: 'Synthetic validate', manifest, has_trades: false, rule_test: null } }))
  await page.route(`**/api/runs/${runId}/figures`, route => route.fulfill({ json: { run_id: runId, items: [] } }))
  await page.route(`**/api/runs/${runId}/nulls`, route => withData
    ? route.fulfill({ json: { tiers: [
      { tier: 'returns_level', statistics: Array.from({ length: 200 }, (_, i) => Math.sin(i * 1.7) * 0.4 + (i % 7) * 0.03) },
      { tier: 'full_engine', statistics: [-0.41, -0.1, 0.2, 0.74] },
    ] } })
    : route.fulfill({ status: 404, json: { detail: 'no null distributions for this run' } }))
  await page.route('**/api/candles/AAPL**', route => prices === 'error'
    ? route.fulfill({ status: 500, json: { detail: 'store unavailable' } })
    : route.fulfill({ json: {
      symbol: 'AAPL', snapshot_id: null, provenance: {}, paper_markers: [],
      bars: prices === 'empty' ? [] : Array.from({ length: 2500 }, (_, i) => { const c = 100 + i * 0.05 + Math.sin(i / 40) * 8; return { t: (START + i * DAY) / 1000, o: c, h: c, l: c, c, v: 1 } }),
    } }))
  await page.goto(`/#run=${runId}`)
  await page.getByRole('button', { name: 'Gates', exact: true }).click()
}

test('each check card shows a small chart of its own run, with plain labels and a text alternative', async ({ page }) => {
  await openRun(page, dated(false), true)
  const walk = page.locator('.explain-card').nth(0).getByRole('group', { name: /Price of the asset from 2015-01-02/ })
  await expect(walk).toBeVisible()
  await expect(walk).toHaveAttribute('aria-label', /warm-up: rules fixed, nothing re-tuned before each of 31 tested windows/)
  await expect(page.locator('.explain-card').nth(0)).toContainText('tested here, not seen before')
  await expect(page.locator('.explain-card').nth(0)).toContainText('The rules never change in this test.')
  await expect(page.locator('.explain-card').nth(0)).not.toContainText('tuned and tested periods overlap')
  const luck = page.locator('.explain-card').nth(1)
  await expect(luck.getByRole('img')).toHaveCount(2)
  await expect(luck).toContainText('only 4 random series: a rough picture')
  await expect(luck.locator('.cc-tick')).toHaveCount(4)
  await expect(luck).toContainText('this strategy')
  await expect(page.locator('.explain-card').nth(2).getByRole('img', { name: /95% interval from -0\.31 to 0\.84; the interval includes zero/ })).toBeVisible()
  await expect(page.locator('.explain-card').nth(3).getByRole('img', { name: /best Sharpe expected from luck across 1 counted test/ })).toBeVisible()
  await expect(page.locator('.explain-card').nth(3)).toContainText('is a probability from 0 to 1, not a Sharpe ratio.')
  await expect(page.locator('.explain-card').nth(3)).toContainText('per trading period')
  await expect(page.locator('.explain-card').nth(3)).toContainText('(per year:')
  await expect(page.locator('.explain-card').nth(4)).toContainText('mean ± one standard deviation')
  await expect(page.locator('.explain-card').nth(4)).not.toContainText(/interval/i)
  await expect(page.locator('.explain-card').nth(4)).toContainText('the Sharpe of each split is not stored')
  const heights = await page.locator('.check-chart svg').evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect().height))
  expect(Math.max(...heights.slice(1))).toBeLessThanOrEqual(170)
  expect(heights[0]).toBeGreaterThan(0)
  const shown = (await page.locator('.gate-cards').innerText()).replace(/old grade/gi, '')
  expect(shown.match(BANNED)?.[0], shown.slice(Math.max(0, shown.search(BANNED) - 60), shown.search(BANNED) + 40)).toBeUndefined()
})

test('a fold whose training dates run into its tested dates shows a labelled warning band', async ({ page }) => {
  await openRun(page, dated(true), true)
  const card = page.locator('.explain-card').nth(0)
  await expect(card.locator('.cc-overlap')).toHaveCount(1)
  await expect(card).toContainText('Warning: tuned and tested periods overlap')
})

test('an old run without fold dates or draws says what is not recorded, and still draws the other charts', async ({ page }) => {
  await openRun(page, base, false)
  await expect(page.locator('.explain-card').nth(0)).toContainText('Chart not available: the fold dates were not recorded for this run.')
  await expect(page.locator('.explain-card').nth(1)).toContainText('Chart not available: the random-price draws were not recorded for this run.')
  await expect(page.locator('.explain-card').nth(2).getByRole('img')).toBeVisible()
  await expect(page.locator('.explain-card').nth(3).getByRole('img')).toBeVisible()
})

test('the walk-forward chart puts a band and a Sharpe on the price, and a collapsible staircase under it', async ({ page }) => {
  await openRun(page, dated(false), true)
  const card = page.locator('.explain-card').nth(0)
  await expect(card.locator('.cc-fold')).toHaveCount(31)
  await expect(card.locator('.cc-stair-test')).toHaveCount(5)
  await expect(card).toContainText('\u2026 31 folds in total')
  await expect(card).toContainText('before the first test')
  await card.getByRole('button', { name: 'show all folds' }).click()
  await expect(card.locator('.cc-stair-test')).toHaveCount(31)
  await expect(card.getByRole('button', { name: 'show fewer folds' })).toBeVisible()
  const labels = await card.locator('.cc-fold text').evaluateAll(nodes => nodes.map(node => node.getBoundingClientRect()))
  for (let i = 1; i < labels.length; i += 1) expect(labels[i].left, 'Sharpe labels must not overlap').toBeGreaterThanOrEqual(labels[i - 1].right - 0.5)
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
  await expect(card.locator('.cc-fold').first()).toHaveAttribute('aria-label', /^fold 1: tested 2016-/)
})

test('on a phone the charts fit without sideways scroll', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await openRun(page, dated(true), true)
  await expect(page.locator('.explain-card').nth(0).locator('.cc-fold')).toHaveCount(31)
  // The shell's own menu bar is wider than a phone; the check cards and every chart must still fit the screen.
  const overflow = await page.evaluate(() => ({
    page: Math.max(0, (document.querySelector('.gate-cards')?.getBoundingClientRect().right ?? 0) - window.innerWidth),
    wide: Array.from(document.querySelectorAll('.check-chart svg')).filter(svg => svg.getBoundingClientRect().right > window.innerWidth + 1).length,
  }))
  expect(overflow.page).toBeLessThanOrEqual(0)
  expect(overflow.wide).toBe(0)
})

for (const prices of ['error', 'empty'] as const) {
  test(`without stored bars (${prices}) the staircase and bands still draw, and the price says why it is missing`, async ({ page }) => {
    await openRun(page, dated(false), true, prices)
    const card = page.locator('.explain-card').nth(0)
    await expect(card).toContainText('Price not available: no stored bars for AAPL.')
    await expect(card.locator('.cc-fold')).toHaveCount(31)
    await expect(card.locator('.cc-stair-test')).toHaveCount(5)
    await expect(card).not.toContainText('Loading chart')
  })
}

test('a failed draws read says what is missing instead of loading forever', async ({ page }) => {
  await openRun(page, dated(false), false)
  const luck = page.locator('.explain-card').nth(1)
  await expect(luck).toContainText('Chart not available: the random-price draws were not recorded for this run.')
  await expect(luck).not.toContainText('Loading chart')
})
