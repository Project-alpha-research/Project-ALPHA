import { expect, test, type Route } from '@playwright/test'
import { preparePage, openDeskTool } from './support/workstationHarness'

const rule = (name: string) => ({ name, spec_name: name, sha256: 'a'.repeat(64), history: 60, warmup: 20, long_conditions: ['close > sma:20'], short_conditions: [], error: null, spec: { name, long_when: [{ left: { source: 'close' }, op: '>', right: { indicator: 'sma', params: [20] } }], short_when: [] } })

for (const newer of ['edit', 'load'] as const) {
  test(`late automatic rule load cannot overwrite a newer ${newer}`, async ({ page }) => {
    await preparePage(page)
    await page.route('**/api/rules/evaluate', route => route.fulfill({ json: { conditions: [], signal: null, error: 'Fixture has no evaluated bar' } }))
    await page.route('**/api/rules', route => route.fulfill({ json: { rules: [rule('first'), rule('second')] } }))
    let pending: Route | undefined
    await page.route('**/api/rules/first', route => { pending = route })
    await page.route('**/api/rules/second', route => route.fulfill({ json: rule('second') }))
    await page.goto('/#page=data&pane=PriceChart')
    await openDeskTool(page, 'Research tools')
    await page.getByLabel('Saved conditions', { exact: true }).selectOption('first')
    await page.getByRole('button', { name: 'Edit / test rules' }).click()
    await expect.poll(() => Boolean(pending)).toBe(true)
    const name = page.getByLabel('Display name', { exact: true })
    if (newer === 'edit') await name.fill('Unsaved revision')
    else await page.getByRole('complementary', { name: 'Saved rule sets' }).getByRole('button', { name: 'second second', exact: true }).click()
    await expect(name).toHaveValue(newer === 'edit' ? 'Unsaved revision' : 'second')
    const response = page.waitForResponse('**/api/rules/first')
    await pending!.fulfill({ json: rule('first') })
    await response
    await expect(name).toHaveValue(newer === 'edit' ? 'Unsaved revision' : 'second')
  })
}
