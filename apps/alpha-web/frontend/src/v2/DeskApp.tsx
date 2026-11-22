// The Workstation desk frame: a left rail of seven places, a top bar (title, symbol box, Ctrl+K
// palette, status dot) and the selected place. Only the selected place mounts.

import { useCallback, useEffect, useState, type ReactNode } from 'react'
import { api } from '../api/client'
import { readDeskStatus } from './deskApi'
import { getLinked, setLinked } from '../context/linked'
import { registerNavigator } from '../panels/actions'
import { IdeaWorkspace } from '../panels/idea/IdeaWorkspace'
import { RdAgentPanel } from '../panels/RdAgentPanel'
import { SetupLabPanel } from '../panels/SetupLabPanel'
import { ChartsPage } from './ChartsPage'
import { DeskPalette } from './DeskPalette'
import { parseRoute, placeTitle, PLACES, routeHash, statusDot, type Place, type Route } from './deskModel'
import { HomePage } from './HomePage'
import { Icon, Panel } from './parts'
import { useLoad } from './useLoad'
import { SymbolBox } from './SymbolBox'
import { SystemPage } from './SystemPage'
import { TestsPage } from './TestsPage'

const SYMBOL_KEY = 'alpha.desk.symbol'

function rememberedSymbol(): string | null {
  try { return localStorage.getItem(SYMBOL_KEY) } catch { return null }
}

function Rail({ place, onPlace }: { place: Place; onPlace(place: Place): void }) {
  return <nav className="d-rail" aria-label="Places">
    <div className="d-brand" aria-label="ALPHA">α</div>
    {PLACES.map(item => <a key={item.id} href={routeHash({ place: item.id })} className="d-rail-item" aria-current={item.id === place ? 'page' : undefined}
      onClick={event => { event.preventDefault(); onPlace(item.id) }}>
      <Icon name={item.id} size={20} /><span>{item.label}</span>
    </a>)}
  </nav>
}

function Legacy({ title, children }: { title: string; children: ReactNode }) {
  return <Panel title={title} className="d-legacy-place"><div className="d-legacy">{children}</div></Panel>
}

export function DeskApp() {
  const [route, setRoute] = useState<Route>(() => parseRoute(window.location.hash))
  const [palette, setPalette] = useState(false)
  const symbols = useLoad(() => api.symbols(), 'symbols', 'the stored symbols')
  const status = useLoad(readDeskStatus, 'status', 'the nightly status')
  const symbolList = symbols.state === 'ready' ? symbols.value.symbols : []
  const navigate = useCallback((next: Route) => {
    const hash = routeHash(next)
    if (window.location.hash !== hash) window.location.hash = hash
    setRoute(next)
  }, [])
  const place = (id: Place) => navigate({ place: id, run: null, symbol: id === 'charts' ? route.symbol : null })
  const openRun = useCallback((run: string) => navigate({ place: 'tests', run, symbol: null }), [navigate])
  const openChart = useCallback((symbol: string) => {
    try { localStorage.setItem(SYMBOL_KEY, symbol) } catch { /* The chart still opens without the memory. */ }
    setLinked({ symbol })
    navigate({ place: 'charts', run: null, symbol })
  }, [navigate])
  const openIdea = (card: string) => { window.location.hash = `${routeHash({ place: 'ideas' })}&idea=${encodeURIComponent(card)}`; setRoute(parseRoute(window.location.hash)) }

  useEffect(() => {
    const sync = () => setRoute(parseRoute(window.location.hash))
    window.addEventListener('hashchange', sync)
    return () => window.removeEventListener('hashchange', sync)
  }, [])
  useEffect(() => { document.title = `ALPHA · ${placeTitle(route.place)}` }, [route.place])
  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') { event.preventDefault(); setPalette(value => !value) }
    }
    window.addEventListener('keydown', key)
    return () => window.removeEventListener('keydown', key)
  }, [])
  useEffect(() => {
    const noop = () => undefined
    registerNavigator({
      showChart: () => openChart(getLinked().symbol ?? 'SPY'), showRun: openRun, showStrategyLab: noop, showProjects: noop,
      showResearchSources: noop, showResearchData: noop, showDataSymbol: noop, showProviders: noop, showCompare: noop, showIndicators: noop,
    })
  }, [openChart, openRun])

  const chartSymbol = route.symbol ?? rememberedSymbol() ?? (symbolList.includes('SPY') ? 'SPY' : symbolList[0] ?? null)
  const dot = statusDot(status.state === 'ready' ? status.value : null)
  const ideaKey = new URLSearchParams(window.location.hash.replace(/^#/, '')).get('idea') ?? ''
  return <div className="d-app">
    <a className="d-skip" href="#desk-main" onClick={event => { event.preventDefault(); document.getElementById('desk-main')?.focus() }}>Skip to content</a>
    <Rail place={route.place} onPlace={place} />
    <div className="d-main-col">
      <header className="d-top">
        <h1 className="d-top-title">{placeTitle(route.place)}</h1>
        <SymbolBox symbols={symbolList} current={route.place === 'charts' ? chartSymbol ?? '' : ''} onPick={openChart} />
        <button type="button" className="d-search" onClick={() => setPalette(true)}><Icon name="search" size={16} /><span>Jump to…</span><kbd>Ctrl K</kbd></button>
        <span className="d-grow" />
        {dot ? <button type="button" className={`d-dot ${dot.tone}`} title={dot.text} aria-label={dot.text} onClick={() => place('system')}><i aria-hidden="true" /><span>{dot.tone === 'ok' ? 'Nightly ok' : dot.tone === 'bad' ? 'Nightly problem' : 'Check nightly'}</span></button> : null}
      </header>
      <main id="desk-main" className={`d-content d-place-${route.place}`} tabIndex={-1}>
        {route.place === 'home' ? <HomePage onOpenRun={openRun} onAllTests={() => place('tests')} />
          : route.place === 'tests' ? <TestsPage runId={route.run} onOpen={openRun} onBack={() => place('tests')} />
          : route.place === 'charts' ? (chartSymbol ? <ChartsPage key={chartSymbol} symbol={chartSymbol} reservedStart={status.state === 'ready' ? status.value.reserved_start : null} />
            : <Panel title="Charts"><p className="d-empty">No symbols are stored yet. Pull daily bars for a symbol, then pick it in the box at the top.</p></Panel>)
          : route.place === 'ideas' ? <Legacy title="Ideas"><IdeaWorkspace key={ideaKey} /></Legacy>
          : route.place === 'setup' ? <Legacy title="Setup Lab"><SetupLabPanel /></Legacy>
          : route.place === 'rdagent' ? <Legacy title="RD-Agent runs"><RdAgentPanel /></Legacy>
          : <SystemPage status={status} />}
      </main>
    </div>
    <DeskPalette open={palette} symbols={symbolList} onClose={() => setPalette(false)} onPlace={place} onRun={openRun} onIdea={openIdea} onSymbol={openChart} />
  </div>
}
