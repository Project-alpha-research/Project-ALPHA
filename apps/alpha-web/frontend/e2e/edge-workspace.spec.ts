import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { preparePage, openDeskTool, openTask } from './support/workstationHarness'

const candles = { 'XRP/USDT': Array.from({ length: 60 }, (_, i) => ({ t: 1700000000 + i * 86400, o: 100 + i, h: 102 + i, l: 99 + i, c: 101 + i, v: 1000 })) }
const rule = { name: 'trend', spec_name: 'Trend', sha256: 'a'.repeat(64), history: 60, warmup: 20, long_conditions: ['close > sma:20'], short_conditions: [] }

test('chart checklist reports backend values and dock layout survives navigation', async ({ page }) => {
  await preparePage(page, { candles })
  await page.route('**/api/rules', route => route.fulfill({ json: { rules: [rule] } }))
  let evaluations = 0
  await page.route('**/api/rules/evaluate', route => {
    evaluations++
    return route.fulfill({ json: { schema_version: 1, rules_id: 'trend', rules_sha256: rule.sha256, symbol: 'XRP/USDT', as_of: '2024-01-01', bar_ts: 1704067200, signal: 1, error: null, authority: 'none', conditions: [{ side: 'long', index: 0, label: 'close > sma:20', left: 160, right: 150, status: 'pass', reason: null }] } })
  })
  await page.goto('/#page=data&pane=PriceChart')
  await openDeskTool(page, 'Research tools')
  await page.getByLabel('Saved conditions', { exact: true }).selectOption('trend')
  await expect(page.getByRole('region', { name: 'Condition checklist' })).toContainText('160 / 150')
  await expect(page.getByRole('region', { name: 'Condition checklist' })).toContainText('Long condition')
  expect(evaluations).toBe(1)
  await page.getByRole('tab', { name: 'Indicators', exact: true }).click()
  await expect(page.getByRole('textbox', { name: 'Search indicators' })).toBeVisible()
  await openTask(page, 'Research', 'Literature')
  await openTask(page, 'Data & Assets', 'Price')
  await expect(page.getByRole('tab', { name: 'Indicators', exact: true })).toHaveAttribute('aria-selected', 'true')
  await openDeskTool(page, 'Workspace results')
  await page.getByRole('tab', { name: 'Scan results', exact: true }).press('ArrowRight')
  await expect(page.getByRole('region', { name: 'Workspace results', exact: true }).getByRole('tab', { name: 'Trades', exact: true })).toBeFocused()
  await expect(page.getByRole('region', { name: 'Recorded trades' })).toContainText('Choose a recorded run')
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width)
  await page.screenshot({ path: `/tmp/alpha-edge-workspace-${test.info().project.name}.png`, fullPage: true })
  const accessibility = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'wcag22aa']).analyze()
  expect(accessibility.violations).toEqual([])
})
