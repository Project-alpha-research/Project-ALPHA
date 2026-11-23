import { openTask } from './support/workstationHarness'
import { expect, test } from '@playwright/test'
import AxeBuilder from '@axe-core/playwright'
import { writeFile } from 'node:fs/promises'


// The real test store holds crypto pairs: start each journey on the Crypto market.
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    if (!localStorage.getItem('alpha.settings')) localStorage.setItem('alpha.settings', JSON.stringify({ profile: 'crypto', profileChosen: true }))
  })
})

test('real workflow navigation, asset selection, chart and history', async ({ page }) => {
  test.setTimeout(120_000)
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/')
  await expect(page.getByRole('menubar', { name: 'Terminal menu' })).toBeVisible()
  for (const [section, task] of [['Data & Assets', 'Data downloads'], ['Research', 'Ideas'], ['Results', 'All tests'], ['Results', 'Run library'], ['Operations', 'Jobs']]) {
    await openTask(page, section, task)
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width)
    await expect(page.getByText(/panel crashed/i)).toHaveCount(0)
  }
  await page.getByRole('button', { name: 'Symbol, venue and timeframe' }).click()
  const asset = page.getByRole('combobox', { name: 'Active asset' })
  await asset.click()
  await expect(page.getByRole('listbox', { name: 'Stored assets' }).getByRole('option', { name: /BTC\/USDT/ })).toBeVisible({ timeout: 30_000 })
  await asset.fill('BTC')
  await asset.press('Enter')
  await expect(page.getByRole('dialog', { name: 'Working context' })).toHaveCount(0)
  await openTask(page, 'Data & Assets', 'Price')
  await expect(page.getByRole('region', { name: 'Price', exact: true }).locator('.count')).toHaveText('400 bars', { timeout: 30_000 })
  await openTask(page, 'Research', 'Ideas')
  await page.goBack()
  await expect(page.getByRole('tab', { name: 'Price', exact: true })).toHaveAttribute('aria-selected', 'true')
  await page.reload()
  await expect(page.getByRole('button', { name: 'Symbol, venue and timeframe' })).toContainText('BTCUSDT')
  const axe = await new AxeBuilder({ page }).analyze()
  expect(axe.violations.filter(item => ['serious', 'critical'].includes(item.impact ?? '')), JSON.stringify(axe.violations)).toEqual([])
  expect(errors).toEqual([])
})

test('@reference-only every real workflow task opens in both market profiles', async ({ page }, info) => {
  test.setTimeout(300_000)
  const audit: { profile: string; page: string; task: string; alerts: string[] }[] = []
  const failures: { url: string; status: number }[] = []
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('response', response => { if (response.url().includes('/api/') && response.status() >= 400) failures.push({ url: response.url(), status: response.status() }) })
  await page.goto('/')
  for (const profile of ['crypto', 'equities']) {
    await page.getByLabel('Market profile').selectOption(profile)
    for (const section of ['Data & Assets', 'Research', 'Results', 'Operations']) {
      await page.getByRole('menuitem', { name: 'View', exact: true }).click()
      const titles = (await page.locator('.menu-pop .menu-item').allTextContents()).filter(t => t.startsWith(`${section} › `)).map(t => t.slice(`${section} › `.length))
      expect(titles.length).toBeGreaterThan(0)
      await page.keyboard.press('Escape')
      for (const title of titles) {
        await openTask(page, section, title)
        await expect(page.locator('.document-tabs').getByRole('tab', { name: title, exact: true })).toHaveAttribute('aria-selected', 'true')
        await expect(title === 'Price' ? page.locator('.chart-document') : page.locator('.workflow-panel')).toBeVisible()
        await page.waitForTimeout(350)
        await expect(page.getByText(/panel crashed/i)).toHaveCount(0)
        audit.push({ profile, page: section, task: title, alerts: await page.getByRole('alert').allTextContents() })
      }
      await page.screenshot({ path: info.outputPath(`${profile}-${section.replaceAll(/[^a-z]/gi, '-')}.png`) })
    }
  }
  const inventory = info.outputPath('real-task-inventory.json')
  await writeFile(inventory, JSON.stringify({ audit, failures, errors }, null, 2))
  await info.attach('real-task-inventory', { path: inventory, contentType: 'application/json' })
  expect(errors).toEqual([])
  // Both markets show the same tasks since the crypto-only windows were removed.
  expect(audit.filter(item => item.profile === 'crypto').length).toBeGreaterThan(14)
  expect(audit.filter(item => item.profile === 'equities').length).toBe(audit.filter(item => item.profile === 'crypto').length)
  expect(failures).toEqual([])
  expect(audit.filter(item => item.alerts.length)).toEqual([])
})
