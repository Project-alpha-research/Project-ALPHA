// The top-bar symbol box: type-ahead over the symbols in the stored data; Enter opens the chart.

import { useId, useState } from 'react'
import { matchSymbols } from './deskModel'

export function SymbolBox({ symbols, current, onPick }: { symbols: readonly string[]; current: string; onPick(symbol: string): void }) {
  const [text, setText] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const list = useId()
  const matches = matchSymbols(symbols, text)
  const pick = (symbol: string | undefined) => {
    if (!symbol) return
    onPick(symbol); setText(''); setOpen(false); setActive(0)
  }
  return <div className="d-symbol">
    <input className="d-symbol-input mono" role="combobox" aria-label="Symbol" aria-expanded={open && matches.length > 0} aria-controls={list}
      aria-activedescendant={open && matches[active] ? `${list}-${active}` : undefined} placeholder={current || 'Symbol…'} value={text}
      onFocus={() => setOpen(true)} onBlur={() => window.setTimeout(() => setOpen(false), 120)}
      onChange={event => { setText(event.target.value); setActive(0); setOpen(true) }}
      onKeyDown={event => {
        if (event.key === 'ArrowDown') { event.preventDefault(); setActive(index => Math.min(index + 1, matches.length - 1)) }
        if (event.key === 'ArrowUp') { event.preventDefault(); setActive(index => Math.max(index - 1, 0)) }
        if (event.key === 'Enter') { event.preventDefault(); pick(matches[active]) }
        if (event.key === 'Escape') { setOpen(false); event.currentTarget.blur() }
      }} />
    {open && matches.length ? <ul id={list} className="d-symbol-list" role="listbox" aria-label="Stored symbols">
      {matches.map((symbol, index) => <li key={symbol} id={`${list}-${index}`} role="option" aria-selected={index === active}
        className={index === active ? 'active' : undefined} onMouseDown={event => { event.preventDefault(); pick(symbol) }}>
        <span className="mono">{symbol}</span>{symbol === current ? <span className="d-muted">on chart</span> : null}
      </li>)}
    </ul> : null}
  </div>
}
