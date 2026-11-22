// The run's stored figures as plain | annotated pairs, two columns, white paper on the dark desk
// (owner decision). Metadata loads two at a time; a full-screen viewer steps with the arrow keys.

import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { FigureCatalogueItem, FigureMetadata } from '../api/types'
import { plainError, stepIndex } from './deskModel'
import { Icon, Problem, Skeleton } from './parts'

type Pair = { plain: FigureMetadata; annotated: FigureMetadata | null } | { error: string }
type Variant = 'plain' | 'annotated'

function whyUnavailable(reason: string | null): string {
  if (!reason) return 'This chart is not available for this run.'
  if (reason.startsWith('artifact_missing:')) return `This run did not record ${reason.slice('artifact_missing:'.length)}.`
  if (reason.startsWith('artifact_empty:')) return 'Nothing to draw: the run wrote an empty file for this chart.'
  if (reason === 'snapshot_unavailable') return 'This run has no frozen snapshot, so its price bars cannot be drawn exactly.'
  return 'This chart is not available for this run.'
}

/** Loads the pairs in order, two requests at a time, so the first rows appear first. */
function usePairs(runId: string, items: readonly FigureCatalogueItem[]): Record<string, Pair> {
  const [pairs, setPairs] = useState<Record<string, Pair>>({})
  useEffect(() => {
    let live = true
    setPairs({})
    const queue = items.filter(item => item.available)
    const next = async (): Promise<void> => {
      const item = queue.shift()
      if (!item || !live) return
      try {
        const [plain, annotated] = await Promise.all([
          api.figureMetadata(runId, item.figure_id, 'plain'),
          api.figureMetadata(runId, item.figure_id, 'annotated').catch(() => null),
        ])
        if (live) setPairs(previous => ({ ...previous, [item.figure_id]: { plain, annotated } }))
      } catch (cause: unknown) {
        if (live) setPairs(previous => ({ ...previous, [item.figure_id]: { error: plainError(cause, 'this chart') } }))
      }
      return next()
    }
    void Promise.all([next(), next()])
    return () => { live = false }
  }, [runId, items])
  return pairs
}

function Viewer({ shots, index, onIndex, onClose }: { shots: { meta: FigureMetadata; variant: Variant }[]; index: number; onIndex(i: number): void; onClose(): void }) {
  const close = useRef<HTMLButtonElement>(null)
  const shot = shots[index]
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    close.current?.focus()
    const key = (event: KeyboardEvent) => {
      if (event.key === 'Escape') { event.preventDefault(); onClose() }
      if (event.key === 'ArrowRight') { event.preventDefault(); onIndex(stepIndex(index, 1, shots.length)) }
      if (event.key === 'ArrowLeft') { event.preventDefault(); onIndex(stepIndex(index, -1, shots.length)) }
    }
    window.addEventListener('keydown', key)
    return () => { window.removeEventListener('keydown', key); opener?.focus?.() }
  }, [index, shots.length, onIndex, onClose])
  if (!shot) return null
  return <div className="d-viewer" role="dialog" aria-modal="true" aria-label={`${shot.meta.title}, ${shot.variant}`}>
    <header className="d-viewer-head">
      <strong>{shot.meta.title}</strong><span className="d-muted">{shot.variant === 'plain' ? 'Plain' : 'Annotated'} · {index + 1} of {shots.length} · ← → to move, Esc to close</span>
      <span className="d-grow" />
      <button type="button" className="d-icon-btn" aria-label="Previous chart" onClick={() => onIndex(stepIndex(index, -1, shots.length))}><Icon name="left" /></button>
      <button type="button" className="d-icon-btn" aria-label="Next chart" onClick={() => onIndex(stepIndex(index, 1, shots.length))}><Icon name="right" /></button>
      <button ref={close} type="button" className="d-icon-btn" aria-label="Close full screen" onClick={onClose}><Icon name="close" /></button>
    </header>
    <div className="d-viewer-body"><img src={shot.meta.image_url} alt={shot.meta.alt_text} /></div>
    <p className="d-viewer-foot">{shot.meta.plain_language_answer}</p>
  </div>
}

export function FigureGallery({ runId, items }: { runId: string; items: readonly FigureCatalogueItem[] }) {
  const pairs = usePairs(runId, items)
  const [open, setOpen] = useState<number | null>(null)
  const shots = items.flatMap(item => {
    const pair = pairs[item.figure_id]
    if (!pair || 'error' in pair) return []
    return [{ meta: pair.plain, variant: 'plain' as Variant }, ...(pair.annotated ? [{ meta: pair.annotated, variant: 'annotated' as Variant }] : [])]
  })
  const openShot = (meta: FigureMetadata) => setOpen(shots.findIndex(shot => shot.meta === meta))
  return <div className="d-gallery">
    <div className="d-gallery-head" aria-hidden="true"><span>Plain</span><span>Annotated</span></div>
    {items.map(item => {
      const pair = pairs[item.figure_id]
      return <figure key={item.figure_id} className="d-fig" aria-label={item.title}>
        <figcaption><strong>{item.title}</strong><span className="d-muted">{item.summary}</span></figcaption>
        {!item.available ? <p className="d-fig-missing">{whyUnavailable(item.unavailable_reason)}</p>
          : !pair ? <div className="d-fig-pair"><div className="d-fig-wait"><Skeleton rows={1} height={180} label={`Loading ${item.title}`} /></div><div className="d-fig-wait"><Skeleton rows={1} height={180} label={`Loading ${item.title}, annotated`} /></div></div>
          : 'error' in pair ? <Problem>{pair.error}</Problem>
          : <div className="d-fig-pair">
            {[pair.plain, pair.annotated].map((meta, index) => meta
              ? <button key={index} type="button" className="d-fig-shot" onClick={() => openShot(meta)} aria-label={`Open ${item.title}, ${index ? 'annotated' : 'plain'}, full screen`}>
                <img src={meta.image_url} alt={meta.alt_text} loading="lazy" /><span className="d-fig-zoom"><Icon name="expand" size={16} /></span>
              </button>
              : <p key={index} className="d-fig-missing">No annotated version was stored.</p>)}
          </div>}
        {pair && !('error' in pair) ? <p className="d-fig-answer">{pair.plain.plain_language_answer}</p> : null}
      </figure>
    })}
    {open !== null && open >= 0 ? <Viewer shots={shots} index={open} onIndex={setOpen} onClose={() => setOpen(null)} /> : null}
  </div>
}
