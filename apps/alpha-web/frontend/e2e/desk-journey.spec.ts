import { expect, test, type Page } from '@playwright/test'

// Synthetic API responses check the desk's presentation only; nothing here is a market or research result.
const RUN = 'd'.repeat(16)
const DAY = 86_400
const T0 = Date.UTC(2023, 0, 2) / 1000
const BARS = Array.from({ length: 600 }, (_, i) => {
  const c = 100 + i * 0.1 + Math.sin(i / 9) * 3
  return { t: T0 + i * DAY, o: c - 0.5, h: c + 1, l: c - 1, c, v: 1000 + (i % 7) * 100 }
})
const desk = {
  run_id: RUN, kind: 'runs', mtime: 1_795_300_000, display_name: 'Synthetic rule', symbol: 'SYN', idea: 'Synthetic dip idea',
  rule_name: 'synthetic-dip', first_ts: '2023-01-02T00:00:00+00:00', last_ts: '2023-12-29T00:00:00+00:00', trades: 12, tries: 3,
  oos_sharpe: 0.42, evidence: 'too little to read', spark: [1, 1.02, 1.01, 1.05, 1.08],
}
const series = (() => {
  const ts = Array.from({ length: 60 }, (_, i) => T0 + i * DAY)
  const equity = ts.map((_, i) => 1 + 0.004 * i)
  return {
    run_id: RUN, ts, equity, drawdown: equity.map(() => 0), benchmark: ts.map((_, i) => 1 + 0.003 * i), exposure: null, trades: [],
    bands: { tradable: null, scored: null, folds: [] }, price: { status: 'price_not_saved_with_run', ts: [], close: [] },
    bounds: { points: { original: 60, returned: 60, truncated: false, sampling: 'all' }, trades: { original: 0, returned: 0, truncated: false, cap: 2000 } },
    provenance: { artifact_sha256: {} },
  }
})()
const follow = { as_of: '2026-11-20T01:00:00+00:00', paper: true, followed: 0, behind: 0, markets: [], groups: [], rows: [], notice: 'Paper only. Forward use; not research. Not advice.' }
const market = {
  store: '1D', available_stores: ['1D'], bar_unit: 'day', window: 90, limit: 15, assets_in_store: 1, assets_scanned: 1, scan_cap: 200, bars_cap: 400,
  eligible_assets: 0, data_to: '2024-08-23T00:00:00+00:00', assets: [], too_few_bars: [], unreadable: [], generated_at: '2026-11-19T10:00:00+00:00',
}

async function mockDesk(page: Page): Promise<string[]> {
  const unexpected: string[] = []
  await page.route('**/api/**', route => { unexpected.push(route.request().url()); return route.fulfill({ status: 404, json: { detail: 'not mocked' } }) })
  await page.route('**/api/desk/runs**', route => route.fulfill({ json: { total: 1, items: [desk] } }))
  await page.route('**/api/desk/status', route => route.fulfill({ json: { reserved_start: '2024-01-01', nightly: { date: '2026-11-20', run_number: 1, complete: 'all three paths', blocking: 0, minor: 0, ready: true, reasons: [] }, nightly_problem: null } }))
  await page.route('**/api/symbols', route => route.fulfill({ json: { symbols: ['SYN'] } }))
  await page.route('**/api/market/overview**', route => route.fulfill({ json: market }))
  await page.route('**/api/follow/today**', route => route.fulfill({ json: follow }))
  await page.route('**/api/ideas', route => route.fulfill({ json: { cards: [], total: 0, truncated: false } }))
  await page.route(`**/api/runs/${RUN}`, route => route.fulfill({ json: {
    run_id: RUN, kind: 'runs', display_name: 'Synthetic rule', manifest: { reading: { sentence: 'Synthetic reading sentence.', evidence: { word: 'too little to read', because: ['12 closed trades.'] } } },
    has_trades: true, research_gate_watermark: null,
    rule_test: { name: 'synthetic-dip', idea: 'Synthetic dip idea', rule_sentence: 'Buy after a synthetic dip.', symbol: 'SYN', rule_params: {}, labels: [],
      first_ts: '2023-01-02T00:00:00+00:00', last_ts: '2023-12-29T00:00:00+00:00', fee_bps: 1, slippage_bps: 2, total_trials: 3, diagnostics: null, diagnostics_reason: 'No diagnostic file.' },
  } }))
  await page.route(`**/api/runs/${RUN}/figures`, route => route.fulfill({ json: { run_id: RUN, kind: 'runs', renderer_version: 1, items: [] } }))
  await page.route(`**/api/runs/${RUN}/series**`, route => route.fulfill({ json: series }))
  await page.route(`**/api/runs/${RUN}/trades`, route => route.fulfill({ json: [{ side: 'BUY', quantity: 10, entry_price: 100, exit_price: 104, entry_ts: '2023-03-01T00:00:00+00:00', exit_ts: '2023-03-09T00:00:00+00:00', realized_pnl: 40, realized_return: 0.04 }] }))
  await page.route('**/api/candles/SYN**', route => route.fulfill({ json: { symbol: 'SYN', snapshot_id: null, provenance: null, bars: BARS, paper_markers: [] } }))
  await page.route('**/api/overlays/SYN**', route => route.fulfill({ json: { symbol: 'SYN', snapshot_id: null, provenance: null, authority: 'none', t: BARS.map(b => b.t), indicators: [], annotations: [] } }))
  return unexpected
}

test('the desk opens Home, a run report and the chart with no console error', async ({ page }) => {
  const errors: string[] = []
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  page.on('pageerror', error => errors.push(error.message))
  const unexpected = await mockDesk(page)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Today', level: 1 })).toBeVisible()
  await expect(page.getByRole('navigation', { name: 'Places' }).getByRole('link')).toHaveCount(7)
  const recent = page.getByRole('region', { name: 'Recent tests' })
  await expect(recent.getByText('Synthetic dip idea')).toBeVisible()
  await expect(recent.getByText('0.42')).toBeVisible()
  await expect(page.getByRole('button', { name: /Last nightly run 2026-11-20/ })).toBeVisible()

  await recent.getByRole('row', { name: /Open the report for Synthetic dip idea/ }).click()
  await expect(page).toHaveURL(new RegExp(`place=tests&run=${RUN}`))
  await expect(page.getByRole('heading', { name: 'Buy after a synthetic dip.' })).toBeVisible()
  await expect(page.getByText('Synthetic reading sentence.')).toBeVisible()
  await expect(page.getByTestId('tear-sheet-stack')).toBeVisible()
  await expect(page.getByRole('region', { name: 'Trades' }).getByRole('cell', { name: '4.00%' })).toBeVisible()

  await page.keyboard.press('Control+K')
  await page.getByRole('option', { name: /SYN.*Open chart/ }).click()
  await expect(page).toHaveURL(/place=charts&symbol=SYN/)
  await expect(page.locator('.d-chart-canvas canvas').first()).toBeVisible()
  await expect(page.getByText('Held back: not used by tests (from 2024-01-01)')).toBeVisible()
  await page.getByRole('button', { name: 'All', exact: true }).click()
  await expect(page.getByText(/600 daily bars/)).toBeVisible()
  await expect(page.getByText(/loading…/i)).toHaveCount(0)
  expect(unexpected).toEqual([])
  expect(errors).toEqual([])
})

test('the old shell stays reachable at #legacy', async ({ page }) => {
  await page.goto('/#legacy')
  await expect(page.getByRole('menubar', { name: 'Terminal menu' })).toBeVisible()
  await expect(page.locator('html')).not.toHaveAttribute('data-desk', 'v2')
})
