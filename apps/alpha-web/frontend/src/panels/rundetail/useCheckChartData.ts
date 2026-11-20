import { useEffect, useMemo, useState } from 'react'

import { api } from '../../api/client'
import type { NullTiers } from '../../api/types'
import type { ValidateManifest } from '../../explain/types'
import type { PriceBar } from './checkChartModel'

/** One read, owned by the load that asked for it. A failed read is "missing", never an empty chart. */
export type Read<T> = { state: 'loading' } | { state: 'ready'; value: T } | { state: 'missing' }
interface Owned<T> {
  load: () => Promise<T>
  read: Read<T>
}

const READ_LIMIT_MS = 20_000

/** Rejects when `load` has not answered in `ms`, so a chart never waits forever. */
export function withTimeout<T>(load: () => Promise<T>, ms: number): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error('the read did not answer in time')), ms)
    load().then(
      (value) => { clearTimeout(timer); resolve(value) },
      (error: unknown) => { clearTimeout(timer); reject(error) },
    )
  })
}

function useOwned<T>(load: () => Promise<T>): Read<T> {
  const [owned, setOwned] = useState<Owned<T> | null>(null)
  useEffect(() => {
    let live = true
    withTimeout(load, READ_LIMIT_MS).then(
      (value) => live && setOwned({ load, read: { state: 'ready', value } }),
      () => live && setOwned({ load, read: { state: 'missing' } }),
    )
    return () => { live = false }
  }, [load])
  return owned?.load === load ? owned.read : { state: 'loading' }
}

const day = (iso: unknown): string | null => (typeof iso === 'string' && /^\d{4}-\d{2}-\d{2}/.test(iso) ? iso.slice(0, 10) : null)

/**
 * The asset's stored daily bars between the run's own first and last recorded dates (`GET /api/candles`, the
 * point-in-time read, cut at the run's last date, or its research cutoff when that is earlier, so nothing after the run's
 * window is asked for or drawn). Resolves null when the run does not name its asset, dates or home store.
 */
export function loadBars(manifest: ValidateManifest): Promise<PriceBar[] | null> {
  const metadata = (manifest.metadata ?? {}) as Record<string, unknown>
  const spine = (manifest as { spine?: { store?: unknown } }).spine
  const symbol = typeof metadata.symbol === 'string' ? metadata.symbol : null
  const start = day(metadata.first_ts)
  // A run held back from the reserved period names its research cutoff; never ask past it, whatever the last date says.
  const lastDay = day(metadata.last_ts)
  const cutoff = day(manifest.research_cutoff)
  const end = lastDay && cutoff && cutoff < lastDay ? cutoff : lastDay
  const homeStore = spine?.store === undefined || spine.store === 'home'
  if (!symbol || !start || !end || !homeStore) return Promise.resolve(null)
  const query = `?${new URLSearchParams({ start, end }).toString()}`
  return api.candles(symbol, query).then((candles) => candles.bars.map((b) => ({ t: b.t, c: b.c })))
}

/** The two reads the charts need. Each is owned by the run and manifest that asked, so a run switch never shows old data. */
export function useCheckChartData(runId: string, manifest: ValidateManifest): { bars: Read<PriceBar[] | null>; nulls: Read<NullTiers> } {
  const loadPrice = useMemo(() => () => loadBars(manifest), [manifest])
  const loadNulls = useMemo(() => (): Promise<NullTiers> => api.nulls(runId), [runId])
  return { bars: useOwned(loadPrice), nulls: useOwned(loadNulls) }
}
