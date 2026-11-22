import type { ArchiveChartDataset } from '../api/client'
import { archivePairLabel } from '../components/assetChoices'
import { openArchiveMarket, openStoredMarket } from '../panels/actions'
/**
 * One context control, replacing five.
 *
 * The old top bar carried DESK, LINK, SYM, ASOF and a six-field PRJ/VER/UNI/TF/SNAP/RUN
 * strip, each its own popover. That is a lot of chrome for state that is really one thing:
 * *what am I looking at*. The chip reads the artboard way — `BTCUSDT · Binance · D1` — and
 * opens a single editor for the symbol and the date window.
 *
 * The A/B/C/D link groups are gone. They let panels follow different contexts inside one
 * desk, which only made sense when you could tile arbitrary panels; with one context per
 * screen the mechanism cost more comprehension than it bought.
 */

import { AssetSelect } from '../components/AssetSelect'
import { useEffect, useRef, useState } from 'react'

import { setLinked, useLinked } from '../context/linked'
import { displaySymbol } from '../panels/marketWatchModel'
import { useStoredVenues } from '../context/storedQuotes'

export function ContextBar({ archive = null }: { archive?: ArchiveChartDataset | null }) {
  const linked = useLinked()
  const venues = useStoredVenues()
  const venue = archive?.venue ?? (linked.symbol ? venues[linked.symbol] : null)
  const [open, setOpen] = useState(false)
  const wrap = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDown = (event: MouseEvent) => {
      if (wrap.current && !wrap.current.contains(event.target as Node)) setOpen(false)
    }
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  return (
    <div className="context" ref={wrap} style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
      <button
        className="context-chip"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        aria-label="Symbol, venue and timeframe"
        title={`What every document is showing · ${linked.start ?? 'start'} → ${linked.end ?? 'latest'}${linked.runId ? ` · run ${linked.runId.slice(0, 8)}` : ''}`}
      >
        <span className="context-symbol">{archive ? archivePairLabel(archive) : linked.symbol ? displaySymbol(linked.symbol) : 'no symbol'}</span>
        {venue ? (
          <>
            <span className="context-sep">·</span>
            <span className="context-venue">{venue}</span>
          </>
        ) : null}
        <span className="context-sep">·</span>
        <span className="context-tf">{archive?.frequency ?? 'D1'}</span>
        <span className="context-caret" aria-hidden="true">▾</span>
      </button>

      {open ? (
        <div className="context-pop" role="dialog" aria-label="Working context">
          <label>
            <span className="eyebrow">Symbol</span>
            <AssetSelect value={archive ? archivePairLabel(archive) : linked.symbol ?? ''} label="Active asset" onChange={symbol => { openStoredMarket(symbol); setOpen(false) }} onArchiveSelect={dataset => { openArchiveMarket(dataset); setOpen(false) }} />
          </label>
          <div className="context-pair">
            <label>
              <span className="eyebrow">From</span>
              <input
                className="field"
                type="date"
                value={linked.start ?? ''}
                onChange={(event) => setLinked({ start: event.target.value || null })}
              />
            </label>
            <label>
              <span className="eyebrow">To (as-of)</span>
              <input
                className="field"
                type="date"
                value={linked.end ?? ''}
                onChange={(event) => setLinked({ end: event.target.value || null })}
              />
            </label>
          </div>
          <label className="advanced-only">
            <span className="eyebrow">Strategy version</span>
            <input
              className="field mono"
              value={linked.versionId ?? ''}
              placeholder="version id"
              onChange={(event) => setLinked({ versionId: event.target.value || null })}
            />
          </label>
          <label className="advanced-only">
            <span className="eyebrow">Data snapshot</span>
            <input
              className="field mono"
              value={linked.snapshotId ?? ''}
              placeholder="snapshot id"
              onChange={(event) => setLinked({ snapshotId: event.target.value || null })}
            />
          </label>
          {/* The run is part of what you are looking at -- the price chart overlays its
              causal trace -- so this is where you set or clear one without going back to the
              Navigator. */}
          <label className="advanced-only">
            <span className="eyebrow">Run</span>
            <input
              className="field mono"
              value={linked.runId ?? ''}
              placeholder="run id"
              spellCheck={false}
              onChange={(event) => setLinked({ runId: event.target.value.trim() || null })}
            />
          </label>
          <p className="context-note muted">
            {archive ? `Archive chart: ${archive.venue} · ${archive.market_type} · ${archive.frequency}. Strategy context remains ${linked.symbol ?? 'unselected'}.` : 'Stored daily bars. Select a pair and then its source / native interval when offered.'}
          </p>
          <div className="context-actions">
            <button
              className="btn ghost"
              onClick={() => setLinked({ start: null, end: null, runId: null })}
            >
              Clear window
            </button>
            <button className="btn primary" onClick={() => setOpen(false)}>
              Done
            </button>
          </div>
        </div>
      ) : null}
    </div>
  )
}
