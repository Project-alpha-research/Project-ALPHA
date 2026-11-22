import { expect, test } from '@playwright/test'

test('the top-bar theme survives a reload', async ({ page }) => {
  await page.goto('/#legacy')
  const theme = page.getByRole('combobox', { name: 'Theme', exact: true })
  await expect(theme).toHaveValue('light')
  await theme.selectOption('dim')
  await page.reload()
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dim')
  await expect(theme).toHaveValue('dim')
})
