import './MarketOverview.css'
// Market overview: a display of stored market data, not a research result. The server sends every
// number (`GET /api/market/overview`); this file lays them out as small multiples on one scale.

import { useEffect, useMemo, useState } from 'react'

import { api } from '../api/client'
import type { MarketAsset, MarketOverview as Overview } from '../api/types'
import { useAreaVersion } from '../state/activity'
import { openStoredMarket } from './actions'
import {
  WINDOWS, commonScale, differsMost, fmtBarDate, fmtPct, fmtPrice, fmtRatio, fmtVolume, hoverState, linePoints,
  sortAssets, standsOut, unitLabels, type SortDirection, type SortKey,
} from './marketModel'

const TILE_W = 120
const TILE_H = 44
const ALL_W = 640
const ALL_H = 240

interface SortState { key: SortKey; direction: SortDirection }

export interface MarketViewProps {
  data: Overview | null
  error: string | null
  loading: boolean
  store: string
  window: number
  onStore(store: string): void
  onWindow(window: number): void
  onOpen(asset: string): void
  initialSort?: SortState
}

const glyph = (value: number) => (value > 0 ? '▲' : value < 0 ? '▼' : '•')

function Change({ value }: { value: number }) {
  return <span className="market-change"><span aria-hidden="true">{glyph(value)} </span>{fmtPct(value)}</span>
}

function Tile({ item, scale, differs, hovered, onOpen, onHover }: {
  item: MarketAsset; scale: [number, number]; differs: boolean; hovered: string | null
  onOpen(asset: string): void; onHover(asset: string | null): void
}) {
  return (
    <button
      type="button" className="market-tile" data-asset={item.asset} data-differs={differs ? 'true' : undefined}
      data-hover={hoverState(hovered, item.asset)}
      aria-label={`${item.asset}, last ${fmtPrice(item.last_close)}, window change ${fmtPct(item.change_window_pct)}${differs ? ', differs most from the group' : ''}. Opens the chart.`}
      onClick={() => onOpen(item.asset)} onMouseEnter={() => onHover(item.asset)} onMouseLeave={() => onHover(null)}
      onFocus={() => onHover(item.asset)} onBlur={() => onHover(null)}
    >
      <span className="market-tile-head">
        <strong>{item.asset}</strong>
        {differs ? <span className="market-badge">Differs most</span> : null}
      </span>
      <svg viewBox={`0 0 ${TILE_W} ${TILE_H}`} className="market-spark" aria-hidden="true" preserveAspectRatio="none">
        <line x1="0" x2={TILE_W} y1={linePoints([100], scale, 1, TILE_H).split(',')[1]} y2={linePoints([100], scale, 1, TILE_H).split(',')[1]} className="market-base" />
        <polyline points={linePoints(item.series, scale, TILE_W, TILE_H)} className="market-spark-line" />
      </svg>
      <span className="market-tile-foot">
        <span className="num">{fmtPrice(item.last_close)}</span>
        <Change value={item.change_window_pct} />
      </span>
    </button>
  )
}

function AllLines({ assets, scale, hovered, onHover }: {
  assets: MarketAsset[]; scale: [number, number]; hovered: string | null; onHover(asset: string | null): void
}) {
  const active = assets.find(item => item.asset === hovered)
  return (
    <section aria-labelledby="market-all-title" className="market-all">
      <h3 id="market-all-title">All lines</h3>
      <svg viewBox={`0 0 ${ALL_W} ${ALL_H}`} preserveAspectRatio="none" role="img" className="market-all-svg"
        aria-label="All assets on one chart. Each line is the close, 100 at the start of the window. The table below has the numbers.">
        <line x1="0" x2={ALL_W} y1={linePoints([100], scale, 1, ALL_H).split(',')[1]} y2={linePoints([100], scale, 1, ALL_H).split(',')[1]} className="market-base" />
        {assets.map(item => (
          <polyline key={item.asset} points={linePoints(item.series, scale, ALL_W, ALL_H)}
            className={`market-line market-line-${hoverState(hovered, item.asset)}`} />
        ))}
        {assets.map(item => (
          <polyline key={`hit-${item.asset}`} points={linePoints(item.series, scale, ALL_W, ALL_H)} className="market-line-hit"
            onMouseEnter={() => onHover(item.asset)} onMouseLeave={() => onHover(null)} />
        ))}
      </svg>
      <p className="muted" role="status">
        {active ? `${active.asset}: ${fmtPct(active.change_window_pct)} over the window. The other lines are dimmed.` : 'Point at a line, a tile or a name to highlight it.'}
      </p>
      <ul className="market-legend">
        {assets.map(item => (
          <li key={item.asset}>
            <button type="button" className="market-legend-button" data-hover={hoverState(hovered, item.asset)}
              onMouseEnter={() => onHover(item.asset)} onMouseLeave={() => onHover(null)}
              onFocus={() => onHover(item.asset)} onBlur={() => onHover(null)}>{item.asset}</button>
          </li>
        ))}
      </ul>
    </section>
  )
}

function StandsOut({ assets }: { assets: MarketAsset[] }) {
  const found = standsOut(assets)
  return (
    <section aria-labelledby="market-stands-title" className="market-stands">
      <h3 id="market-stands-title">Stands out</h3>
      <ul>
        <li>Volume furthest above usual: {found.volume ? <><strong>{found.volume.asset}</strong>, {fmtRatio(found.volume.volume_vs_median)} its 20-bar median</> : 'none'}</li>
        <li>Largest rise in the window: {found.up ? <><strong>{found.up.asset}</strong>, {fmtPct(found.up.change_window_pct)}</> : 'none'}</li>
        <li>Largest fall in the window: {found.down ? <><strong>{found.down.asset}</strong>, {fmtPct(found.down.change_window_pct)}</> : 'none'}</li>
      </ul>
    </section>
  )
}

function Table({ data, rows, sort, onSort, onOpen, onHover }: {
  data: Overview; rows: MarketAsset[]; sort: SortState; onSort(key: SortKey): void; onOpen(asset: string): void; onHover(asset: string | null): void
}) {
  const unit = unitLabels(data.bar_unit)
  const columns: [SortKey, string, boolean][] = [
    ['asset', 'Asset', false], ['last_close', 'Price', true], ['change_1_pct', unit.one, true], ['change_7_pct', unit.seven, true],
    ['change_window_pct', `${data.window} bars`, true], ['last_volume', 'Volume', true], ['volume_vs_median', 'Volume vs usual', true],
  ]
  return (
    <div className="market-table-wrap">
      <table className="blotter market-table" aria-label="Market overview table">
        <caption className="muted">Volume vs usual is the last bar's volume divided by the median of the 20 bars before it.</caption>
        <thead>
          <tr>
            {columns.map(([key, label, right]) => (
              <th key={key} className={right ? 'r' : undefined} scope="col"
                aria-sort={sort.key === key ? (sort.direction === 'asc' ? 'ascending' : 'descending') : 'none'}>
                <button type="button" className="market-sort" onClick={() => onSort(key)}>
                  {label}{sort.key === key ? (sort.direction === 'asc' ? ' ▲' : ' ▼') : ''}
                </button>
              </th>
            ))}
            <th scope="col">Last bar</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(item => (
            <tr key={item.asset} data-row={item.asset} onMouseEnter={() => onHover(item.asset)} onMouseLeave={() => onHover(null)}>
              <td><button type="button" className="market-row-link" onClick={() => onOpen(item.asset)}>{item.asset}</button></td>
              <td className="num">{fmtPrice(item.last_close)}</td>
              <td className="num"><Change value={item.change_1_pct} /></td>
              <td className="num"><Change value={item.change_7_pct} /></td>
              <td className="num"><Change value={item.change_window_pct} /></td>
              <td className="num">{fmtVolume(item.last_volume)}</td>
              <td className="num">{fmtRatio(item.volume_vs_median)}</td>
              <td className="num">{fmtBarDate(item.last_bar, data.bar_unit)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function MarketView(props: MarketViewProps) {
  const { data, error, loading, store, window, onStore, onWindow, onOpen } = props
  const [sort, setSort] = useState<SortState>(props.initialSort ?? { key: 'asset', direction: 'asc' })
  const [hovered, setHovered] = useState<string | null>(null)
  const assets = useMemo(() => data?.assets ?? [], [data])
  const scale = useMemo(() => commonScale(assets), [assets])
  const differs = useMemo(() => differsMost(assets), [assets])
  const rows = useMemo(() => sortAssets(assets, sort.key, sort.direction), [assets, sort])
  const sortBy = (key: SortKey) => setSort(current => ({ key, direction: current.key === key && current.direction === 'asc' ? 'desc' : 'asc' }))
  const stores = data?.available_stores?.length ? data.available_stores : [store]
  return (
    <div className="market-overview" style={{ background: 'var(--panel)', color: 'var(--ink)', padding: 'var(--pad)' }}>
      <h2>Market</h2>
      <p className="muted">Market view. Not a test result. It shows stored bars only; nothing is fetched or saved.</p>
      <div className="market-controls">
        <label>Bar size <select value={store} onChange={event => onStore(event.target.value)}>
          {stores.map(name => <option key={name} value={name}>{name}</option>)}
        </select></label>
        <label>Window <select value={String(window)} onChange={event => onWindow(Number(event.target.value))}>
          {WINDOWS.map(size => <option key={size} value={size}>{size} bars</option>)}
        </select></label>
      </div>
      {error ? <p role="alert" className="market-error">{error}</p> : null}
      {loading && !data && !error ? <p className="muted" role="status">Loading stored bars…</p> : null}
      {data ? (
        <>
          <p><strong>Data to: {fmtBarDate(data.data_to ?? '', data.bar_unit) || 'no bars'}</strong></p>
          <p className="muted">
            Showing the {assets.length} assets with the highest median traded value (close × volume) over the last {data.window} bars,
            among assets with enough bars. {data.eligible_assets} assets had enough bars.
          </p>
          <p className="muted">
            Scanned {data.assets_scanned} of {data.assets_in_store} assets (cap {data.scan_cap} assets, {data.bars_cap} bars each; assets are taken in name order).
          </p>
          {assets.length === 0 ? <p role="status">No stored bars to show for this bar size and window.</p> : (
            <>
              <StandsOut assets={assets} />
              <p className="muted">Every tile uses the same scale. 100 is the first bar of the window. "Differs most" marks the asset whose window change is furthest from the group median. It is not a judgement.</p>
              <div className="market-grid" role="group" aria-label="One small chart per asset">
                {assets.map(item => (
                  <Tile key={item.asset} item={item} scale={scale} differs={item.asset === differs} hovered={hovered} onOpen={onOpen} onHover={setHovered} />
                ))}
              </div>
              <AllLines assets={assets} scale={scale} hovered={hovered} onHover={setHovered} />
              <Table data={data} rows={rows} sort={sort} onSort={sortBy} onOpen={onOpen} onHover={setHovered} />
            </>
          )}
          {data.too_few_bars.length ? (
            <ul className="muted market-skipped" aria-label="Assets with too few bars">
              {data.too_few_bars.map(item => <li key={item.asset}>{item.asset}: too few bars ({item.bar_count} of {item.needed} needed)</li>)}
            </ul>
          ) : null}
          {data.unreadable.length ? (
            <ul className="muted market-skipped" aria-label="Assets that could not be read">
              {data.unreadable.map(item => <li key={item.asset}>{item.asset}: could not be read ({item.reason})</li>)}
            </ul>
          ) : null}
        </>
      ) : null}
    </div>
  )
}

export function MarketOverview() {
  const [store, setStore] = useState('1D')
  const [window, setWindow] = useState<number>(90)
  const [data, setData] = useState<Overview | null>(null)
  const [error, setError] = useState<string | null>(null)
  const barsVersion = useAreaVersion('bars')
  useEffect(() => {
    let live = true
    setError(null)
    api.marketOverview(store, window).then(
      result => { if (live) setData(result) },
      (cause: unknown) => { if (live) { setData(null); setError(cause instanceof Error ? cause.message : String(cause)) } },
    )
    return () => { live = false }
  }, [store, window, barsVersion])
  const stale = data !== null && (data.store !== store || data.window !== window)
  return (
    <MarketView data={stale ? null : data} error={error} loading={!error && (data === null || stale)} store={store} window={window}
      onStore={setStore} onWindow={setWindow} onOpen={openStoredMarket} />
  )
}
