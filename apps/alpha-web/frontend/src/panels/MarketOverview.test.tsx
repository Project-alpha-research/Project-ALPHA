import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import type { MarketAsset, MarketOverview as Overview } from '../api/types'
import { MarketView } from './MarketOverview'

function asset(name: string, change: number, extra: Partial<MarketAsset> = {}): MarketAsset {
  return {
    asset: name, last_close: 12.5, change_1_pct: 0.4, change_7_pct: 1.5, change_window_pct: change, last_volume: 2500,
    volume_vs_median: 1.1, median_traded_value: 5000, series: [100, 100 + change / 2, 100 + change], series_ts: [1, 2, 3],
    last_bar: '2026-11-18T00:00:00+00:00', bar_count: 120, ...extra,
  }
}

const assets = [
  asset('AAA', 1, { volume_vs_median: 1.2 }), asset('BBB', 2, { volume_vs_median: 6.5 }), asset('CCC', 3),
  asset('DDD', 40), asset('EEE', -9),
]
const data: Overview = {
  store: '1D', available_stores: ['1D', '1h'], bar_unit: 'day', window: 90, limit: 15, assets_in_store: 260, assets_scanned: 200,
  scan_cap: 200, bars_cap: 400, eligible_assets: 5, data_to: '2026-11-18T00:00:00+00:00', assets,
  too_few_bars: [{ asset: 'NEW', bar_count: 12, needed: 90 }], unreadable: [], generated_at: '2026-11-19T10:00:00+00:00',
}

function render(overrides: Partial<Parameters<typeof MarketView>[0]> = {}): string {
  return renderToStaticMarkup(
    <MarketView data={data} error={null} loading={false} store="1D" window={90} onStore={() => undefined}
      onWindow={() => undefined} onOpen={() => undefined} {...overrides} />,
  )
}

describe('Market view', () => {
  it('renders one tile per asset with name, price and window change', () => {
    const html = render()
    expect(html.match(/class="market-tile"/g)).toHaveLength(5)
    expect(html).toContain('data-asset="AAA"')
    expect(html).toContain('12.5')
    expect(html).toContain('+40.00%')
  })

  it('marks only the asset that differs most, in words and not by colour', () => {
    const html = render()
    expect(html.match(/data-differs="true"/g)).toHaveLength(1)
    expect(html).toMatch(/data-asset="DDD"[^>]*data-differs="true"/)
    expect(html.match(/>Differs most</g)).toHaveLength(1)
  })

  it('says what it shows, which assets, and that it is not a test result', () => {
    const html = render()
    expect(html).toContain('Market view. Not a test result.')
    expect(html).toContain('Data to: 2026-11-18')
    expect(html).toContain('highest median traded value')
    expect(html).toContain('Scanned 200 of 260 assets')
    expect(html).toContain('NEW: too few bars (12 of 90 needed)')
    expect(html).toContain('same scale')
  })

  it('lists a short Stands out summary with plain numbers', () => {
    const html = render()
    expect(html).toContain('Stands out')
    expect(html).toMatch(/Volume furthest above usual[\s\S]*BBB[\s\S]*6\.5×/)
    expect(html).toMatch(/Largest rise[\s\S]*DDD/)
    expect(html).toMatch(/Largest fall[\s\S]*EEE/)
  })

  it('has a combined all-lines chart with a text alternative', () => {
    const html = render()
    expect(html).toContain('All lines')
    expect(html.match(/class="market-line/g)?.length).toBeGreaterThanOrEqual(5)
    expect(html).toContain('role="img"')
  })

  it('sorts the table by the chosen column', () => {
    const rows = (html: string) => [...html.matchAll(/data-row="([A-Z]+)"/g)].map(match => match[1])
    expect(rows(render())).toEqual(['AAA', 'BBB', 'CCC', 'DDD', 'EEE'])
    expect(rows(render({ initialSort: { key: 'volume_vs_median', direction: 'desc' } }))).toEqual(['BBB', 'AAA', 'CCC', 'DDD', 'EEE'])
    expect(rows(render({ initialSort: { key: 'change_window_pct', direction: 'asc' } }))).toEqual(['EEE', 'AAA', 'BBB', 'CCC', 'DDD'])
    expect(render({ initialSort: { key: 'change_window_pct', direction: 'asc' } })).toContain('aria-sort="ascending"')
  })

  it('reaches tiles and rows by keyboard', () => {
    const html = render()
    expect(html.match(/<button[^>]*class="market-tile"/g)).toHaveLength(5)
    expect(html.match(/<button[^>]*class="market-row-link"/g)).toHaveLength(5)
    expect(html).toContain('aria-label="AAA, last 12.5')
  })

  it('shows plain-word empty, loading and error states', () => {
    expect(render({ data: { ...data, assets: [], eligible_assets: 0 } })).toContain('No stored bars to show')
    expect(render({ data: null, loading: true })).toContain('Loading stored bars')
    const error = render({ data: null, error: 'Cannot read stored bars' })
    expect(error).toContain('role="alert"')
    expect(error).toContain('Cannot read stored bars')
    expect(error).not.toContain('No stored bars to show')
  })

  it('offers the stored sizes and the three windows', () => {
    const html = render()
    expect(html).toContain('<option value="1h">')
    expect(html).toMatch(/<option value="30"[^>]*>30 bars/)
    expect(html).toMatch(/<option value="365"[^>]*>365 bars/)
  })

  it('gives no advice and uses no profit words', () => {
    expect(render()).not.toMatch(/profit|\bbuy\b|\bsell\b|should|recommend/i)
  })

  it('never shows NaN', () => {
    expect(render({ data: { ...data, assets: [asset('ZZZ', 0, { series: [100, 100, 100], volume_vs_median: null })] } })).not.toContain('NaN')
  })
})
