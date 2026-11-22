// Ctrl+K: jump to a place, an idea, a test or a symbol. The lists load when the palette opens.

import { Command } from 'cmdk'
import { useEffect, useRef, useState } from 'react'
import { api } from '../api/client'
import type { IdeaList } from '../api/types'
import { ideaName, PLACES, type DeskRun, type Place } from './deskModel'
import { readRecentRuns } from './deskApi'

interface Lists { runs: DeskRun[]; ideas: IdeaList['cards'] }

export function DeskPalette({ open, symbols, onClose, onPlace, onRun, onIdea, onSymbol }: {
  open: boolean; symbols: readonly string[]; onClose(): void; onPlace(place: Place): void; onRun(runId: string): void; onIdea(card: string): void; onSymbol(symbol: string): void
}) {
  const [lists, setLists] = useState<Lists | null>(null)
  const [problem, setProblem] = useState<string | null>(null)
  const opener = useRef<HTMLElement | null>(null)
  useEffect(() => {
    if (!open) return
    opener.current = document.activeElement as HTMLElement | null
    let live = true
    Promise.all([readRecentRuns(50, false), api.ideaList()]).then(
      ([runs, ideas]) => { if (live) { setLists({ runs: runs.items, ideas: ideas.cards }); setProblem(null) } },
      () => { if (live) setProblem('Tests and ideas could not be listed. Places and symbols still work.') },
    )
    return () => { live = false; opener.current?.focus?.() }
  }, [open])
  if (!open) return null
  const go = (action: () => void) => { onClose(); action() }
  return <div className="d-palette-scrim" onMouseDown={event => { if (event.target === event.currentTarget) onClose() }}>
    <Command className="d-palette" label="Jump to" loop onKeyDown={event => { if (event.key === 'Escape') { event.preventDefault(); onClose() } }}>
      <Command.Input autoFocus placeholder="Jump to a place, idea, test or symbol…" />
      <Command.List>
        <Command.Empty>Nothing matches. Try fewer letters.</Command.Empty>
        <Command.Group heading="Places">
          {PLACES.map(place => <Command.Item key={place.id} value={`place ${place.label}`} onSelect={() => go(() => onPlace(place.id))}>{place.label}</Command.Item>)}
        </Command.Group>
        <Command.Group heading="Symbols">
          {symbols.map(symbol => <Command.Item key={symbol} value={`symbol ${symbol} chart`} onSelect={() => go(() => onSymbol(symbol))}>
            <span className="mono">{symbol}</span><span className="d-muted">Open chart</span></Command.Item>)}
        </Command.Group>
        {lists ? <Command.Group heading="Tests">
          {lists.runs.map(run => <Command.Item key={run.run_id} value={`test ${ideaName(run)} ${run.symbol ?? ''} ${run.run_id}`} onSelect={() => go(() => onRun(run.run_id))}>
            <span>{ideaName(run)}</span><span className="d-muted mono">{run.symbol} · {run.run_id.slice(0, 8)}</span></Command.Item>)}
        </Command.Group> : null}
        {lists ? <Command.Group heading="Ideas">
          {lists.ideas.map(card => <Command.Item key={card.id} value={`idea ${card.claim} ${card.id}`} onSelect={() => go(() => onIdea(card.id))}>
            <span>{card.claim || card.id}</span></Command.Item>)}
        </Command.Group> : null}
      </Command.List>
      {problem ? <p className="d-palette-note" role="status">{problem}</p> : !lists ? <p className="d-palette-note" role="status">Listing tests and ideas…</p> : null}
    </Command>
  </div>
}
