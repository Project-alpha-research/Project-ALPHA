import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'
import { preparePage, openDocument } from './support/workstationHarness'
import type { components } from '../src/api/generated'

test('archive chart identity stays distinct from the strategy context', async ({ page }) => {
  await preparePage(page)
  const manifest = 'a'.repeat(64)
  const dataset: components['schemas']['ArchiveChartDataset'] = {
    schema_version: 1, provider: 'bybit', venue: 'bybit', market_type: 'inverse',
    family: 'derivative_bars', instrument: 'BTCUSD', base_asset: 'BTC', quote_asset: 'USD',
    frequency: '1h', units: 'quote_price', timestamp_convention: 'interval_start_utc',
    manifest_id: manifest, manifest_ids: [manifest], manifest_count: 1,
    start: '2026-09-01T00:00:00Z', end: '2026-09-01T01:00:00Z',
    row_count: 2, verification: 'metadata_only',
  }
  await page.route('**/api/chart-datasets', route => route.fulfill({ json: { datasets: [dataset], authority: 'none', state: 'available' } }))
  const queries: string[] = []
  await page.route('**/api/candles/BTCUSD?*', route => {
    queries.push(new URL(route.request().url()).searchParams.get('manifest_id') ?? '')
    return route.fulfill({ json: {
      symbol: 'BTCUSD', snapshot_id: null,       bars: [0, 1].map(i => ({ t: 1788220800 + i * 3600, o: 100, h: 110, l: 90, c: 105, v: 1000 })),
      provenance: { source: 'bybit:derivative_bars', venue: 'bybit', timeframe: '1H', snapshot_id: null,
        provenance_sha256: manifest, receipt_id: null, knowledge_cutoff: null, quality_status: 'qualified',
        manifest_id: manifest, market_type: 'inverse', volume_unit: 'quote', history_kind: 'reconstructed_from_verified_archive' },
    } })
  })
  await page.goto('/')
  await openDocument(page, 'Chart')
  await page.getByRole('button', { name: 'External archive…' }).click()
  await page.getByRole('button', { name: 'Open BTCUSD', exact: true }).click()
  const chart = page.getByRole('region', { name: 'Price', exact: true })
  await expect(chart.locator('.count')).toHaveText('2 bars')
  await expect(page.locator('.terminal-titlebar')).toContainText('[BTCUSD,1h]')
  await expect(page.getByRole('button', { name: 'Symbol, venue and timeframe' })).toContainText('BTC/USD')
  await expect(chart.locator('.sym-input')).toHaveAttribute('readonly', '')
  // The source readout is readonly; canonical context remains unchanged.
  await expect(page.getByRole('button', { name: 'Duplicate panel primary' })).toBeEnabled()
  await expect(chart).toContainText('VOLUME · QUOTE ASSET')
  expect(queries).toEqual([manifest])
  await page.getByRole('button', { name: 'Return to stored chart' }).click()
  await expect(page.locator('.terminal-titlebar')).not.toContainText('archive')
  await expect(chart.locator('.sym-input')).toHaveValue('XRP/USDT')
  await expect(page.getByRole('button', { name: 'Duplicate panel primary' })).toBeEnabled()
})

test('archive picker filters by exact native timeframe', async ({ page }) => {
  await preparePage(page)
  const dataset = (frequency: '1h' | '4h', manifest: string): components['schemas']['ArchiveChartDataset'] => ({
    schema_version: 1, provider: 'binance', venue: 'binance', market_type: 'spot',
    family: 'market_bars', instrument: 'BTCUSDT', base_asset: 'BTC', quote_asset: 'USDT',
    frequency, units: 'provider_native_ohlcv', timestamp_convention: 'interval_start_utc',
    manifest_id: manifest, manifest_ids: [manifest], manifest_count: 1,
    start: '2026-09-01T00:00:00Z', end: '2026-09-02T00:00:00Z',
    row_count: 6, verification: 'metadata_only',
  })
  await page.route('**/api/chart-datasets', route => route.fulfill({ json: {
    datasets: [dataset('1h', 'a'.repeat(64)), dataset('4h', 'b'.repeat(64))], authority: 'none', state: 'available',
  } }))
  await page.goto('/#page=data&pane=PriceChart')
  await page.getByRole('button', { name: 'External archive…' }).click()
  await page.getByLabel('Filter archive timeframe').selectOption('4h')
  const picker = page.getByRole('region', { name: 'External archive datasets' })
  await expect(picker.getByRole('row')).toHaveCount(2)
  await expect(picker.getByRole('row').nth(1).getByRole('cell').nth(2)).toHaveText('4h')
})

test('main dropdown groups aliases and opens every archive pair with exact source and interval', async ({ page }) => {
  await preparePage(page)
  await page.route('**/api/symbols', route => route.fulfill({ json: { symbols: ['BTC-USD', 'BTC/USD', 'XRP/USDT'] } }))
  const series = (base: string, frequency: '1h' | '4h', manifest: string): components['schemas']['ArchiveChartDataset'] => ({
    schema_version: 1, provider: 'binance', venue: 'binance', market_type: 'spot', family: 'market_bars',
    instrument: `${base}USDT`, base_asset: base, quote_asset: 'USDT', frequency, units: 'provider_native_ohlcv',
    timestamp_convention: 'interval_start_utc', manifest_id: manifest, manifest_ids: [manifest], manifest_count: 1,
    start: '2026-09-01T00:00:00Z', end: '2026-09-02T00:00:00Z', row_count: 2, verification: 'metadata_only',
  })
  const datasets = Array.from({ length: 50 }, (_, i) => series(i === 0 ? 'ETH' : `COIN${i}`, '1h', String(i).padStart(64, '0')))
  const target = series('ETH', '4h', 'b'.repeat(64))
  datasets.push(target)
  await page.route('**/api/chart-datasets', route => route.fulfill({ json: { datasets, authority: 'none', state: 'available' } }))
  const candleQueries: string[] = []
  await page.route('**/api/candles/ETHUSDT?*', route => {
    candleQueries.push(new URL(route.request().url()).search)
    return route.fulfill({ json: { symbol: 'ETHUSDT', snapshot_id: null, provenance: null,
      bars: [{ t: 1788220800, o: 100, h: 110, l: 90, c: 105, v: 1000 }],
    } })
  })
  await page.goto('/#page=research&pane=IdeaWorkspace')
  await page.getByRole('button', { name: 'Symbol, venue and timeframe' }).click()
  const input = page.getByRole('combobox', { name: 'Active asset' })
  await input.click()
  const list = page.getByRole('listbox', { name: 'Stored assets' })
  await expect(list.getByRole('option')).toHaveCount(52)
  await expect(list.getByRole('option', { name: /^BTC\/USD / })).toHaveCount(1)
  await expect(list.getByRole('option', { name: /^COIN49\/USDT / })).toBeAttached()
  await list.getByRole('option', { name: /^BTC\/USD / }).click()
  await expect(page.getByRole('button', { name: 'Open BTC/USD · Stored BTC-USD · daily', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Open BTC/USD · Stored BTC/USD · daily', exact: true })).toBeVisible()
  await input.fill('ETH')
  await list.getByRole('option', { name: /^ETH\/USDT / }).click()
  await page.getByRole('button', { name: /Open ETH\/USDT · binance · spot · 4h/ }).click()
  await expect(page).toHaveURL(/#page=data&pane=PriceChart/)
  await expect(page.locator('.price-panel .count')).toHaveText('1 bars')
  await expect(page.getByRole('button', { name: 'Symbol, venue and timeframe' })).toContainText('ETH/USDT')
  await expect(page.getByRole('button', { name: 'Symbol, venue and timeframe' })).toContainText('4h')
  expect(candleQueries).toEqual([`?manifest_id=${target.manifest_id}`])
  await page.getByRole('button', { name: 'Symbol, venue and timeframe' }).click()
  await expect(page.getByRole('dialog', { name: 'Working context' })).toContainText('Strategy context remains XRP/USDT')
})

test('an archive read error stays explicit and never falls back to canonical candles', async ({ page }) => {
  await preparePage(page)
  const id = 'd'.repeat(64)
  const dataset = { schema_version: 1, provider: 'binance', venue: 'binance', market_type: 'spot', family: 'market_bars', instrument: 'ETHUSDT', base_asset: 'ETH', quote_asset: 'USDT', frequency: '4h', units: 'provider_native_ohlcv', timestamp_convention: 'interval_start_utc', manifest_id: id, manifest_ids: [id], manifest_count: 1, start: null, end: null, row_count: 2, verification: 'metadata_only' }
  await page.route('**/api/chart-datasets', route => route.fulfill({ json: { datasets: [dataset], authority: 'none', state: 'available' } }))
  const requests: string[] = []
  await page.route('**/api/candles/ETHUSDT**', route => {
    requests.push(new URL(route.request().url()).search)
    return route.fulfill({ status: 422, body: 'Archive integrity failure' })
  })
  await page.goto('/#page=data&pane=PriceChart')
  await page.getByRole('button', { name: 'Symbol, venue and timeframe' }).click()
  await page.getByRole('combobox', { name: 'Active asset' }).click()
  await page.getByRole('option', { name: /^ETH\/USDT / }).click()
  await expect.poll(() => requests).toEqual([`?manifest_id=${id}`])
  await expect(page.locator('.price-panel .placeholder')).toContainText('The Workstation refused this request.')
  await expect(page.locator('.price-panel .count')).toHaveCount(0)
})


test('watchlist picker supports keyboard sources, Escape and discovery retry', async ({ page }) => {
  await preparePage(page)
  await page.route('**/api/symbols', route => route.fulfill({ json: { symbols: ['BTC-USD', 'BTC/USD', 'XRP/USDT'] } }))
  let reads = 0
  await page.route('**/api/chart-datasets', route => {
    reads += 1
    return reads === 1 ? route.fulfill({ status: 503, body: 'Drive unavailable' }) : route.fulfill({ json: { datasets: [], authority: 'none', state: 'unavailable' } })
  })
  await page.goto('/#page=data&pane=PriceChart')
  await page.getByText('Browse all available markets', { exact: true }).click()
  const input = page.getByRole('combobox', { name: 'Available market' })
  await input.click()
  await expect(page.getByRole('alert')).toContainText('Archive discovery failed')
  await page.getByRole('button', { name: 'Retry archive', exact: true }).click()
  await expect(page.getByRole('alert')).toHaveCount(0)
  await input.fill('BTC/USD')
  await input.press('Enter')
  const source = page.getByRole('button', { name: 'Open BTC/USD · Stored BTC-USD · daily', exact: true })
  await expect(source).toBeFocused()
  const accessibility = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21aa', 'best-practice']).analyze()
  expect(accessibility.violations).toEqual([])
  await source.press('Escape')
  await expect(input).toBeFocused()
  await expect(input).toHaveAttribute('aria-expanded', 'false')
  await expect(source).toHaveCount(0)
  await input.click()
  await input.fill('BTC/USD')
  await input.press('Enter')
  await source.press('Enter')
  await expect(page).toHaveURL(/#page=data&pane=PriceChart/)
  await expect(page.locator('.price-panel .sym-input')).toHaveValue('BTC-USD')
})
