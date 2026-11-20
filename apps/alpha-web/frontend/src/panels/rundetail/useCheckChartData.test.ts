import { afterEach, describe, expect, it, vi } from 'vitest'

import { api } from '../../api/client'
import type { Candles } from '../../api/types'
import type { ValidateManifest } from '../../explain/types'
import { loadBars, withTimeout } from './useCheckChartData'

const manifest = (metadata: Record<string, unknown>, extra: Record<string, unknown> = {}): ValidateManifest => ({ metadata, ...extra }) as unknown as ValidateManifest
const named = { symbol: 'AAPL', first_ts: '2015-01-02T00:00:00+00:00', last_ts: '2019-06-28T00:00:00+00:00' }
const reply = { symbol: 'AAPL', snapshot_id: null, provenance: {}, paper_markers: [], bars: [{ t: 1, o: 1, h: 1, l: 1, c: 5, v: 1 }] } as unknown as Candles

afterEach(() => vi.restoreAllMocks())

describe('price request', () => {
  it('asks only for the run own window: from its first date to its last recorded date', async () => {
    const spy = vi.spyOn(api, 'candles').mockResolvedValue(reply)
    expect(await loadBars(manifest(named))).toEqual([{ t: 1, c: 5 }])
    expect(spy).toHaveBeenCalledWith('AAPL', '?start=2015-01-02&end=2019-06-28')
  })

  it('never asks past the day before the held-back period when the run recorded its research cutoff', async () => {
    const spy = vi.spyOn(api, 'candles').mockResolvedValue(reply)
    await loadBars(manifest({ ...named, last_ts: '2024-03-01T00:00:00+00:00' }, { research_cutoff: '2023-12-31' }))
    expect(spy).toHaveBeenCalledWith('AAPL', '?start=2015-01-02&end=2023-12-31')
    spy.mockClear()
    await loadBars(manifest(named, { research_cutoff: '2023-12-31' }))
    expect(spy).toHaveBeenCalledWith('AAPL', '?start=2015-01-02&end=2019-06-28')
  })

  it('does not ask at all without a symbol, two dates or the home store', async () => {
    const spy = vi.spyOn(api, 'candles').mockResolvedValue(reply)
    expect(await loadBars(manifest({ ...named, symbol: undefined }))).toBeNull()
    expect(await loadBars(manifest({ ...named, last_ts: 'x' }))).toBeNull()
    expect(await loadBars(manifest(named, { spine: { store: 'other' } }))).toBeNull()
    expect(spy).not.toHaveBeenCalled()
  })
})

describe('a read that never answers', () => {
  it('gives up after the time allowed, so "Loading chart…" cannot stay forever', async () => {
    vi.useFakeTimers()
    const hung = withTimeout(() => new Promise<never>(() => undefined), 5_000)
    const seen = expect(hung).rejects.toThrow(/did not answer/)
    await vi.advanceTimersByTimeAsync(5_001)
    await seen
    vi.useRealTimers()
  })

  it('passes a quick answer and a quick failure straight through', async () => {
    await expect(withTimeout(() => Promise.resolve(3), 5_000)).resolves.toBe(3)
    await expect(withTimeout(() => Promise.reject(new Error('no')), 5_000)).rejects.toThrow('no')
  })
})
