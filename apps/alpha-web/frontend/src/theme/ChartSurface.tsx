import { useLayoutEffect, useRef, useState, useSyncExternalStore, type CSSProperties, type ReactNode } from 'react'
import { chartRoles, readTokens } from '../util/tokens'
import { darkChart, lightChart, type ChartPalette } from './themes'
import { Palette, useTheme } from './themeState'

const change = 'alpha-chart-theme-change'
function subscribe(listener: () => void) {
  window.addEventListener(change, listener)
  window.addEventListener('storage', listener)
  return () => {
    window.removeEventListener(change, listener)
    window.removeEventListener('storage', listener)
  }
}

function cssTokens(palette: ChartPalette): CSSProperties {
  return Object.fromEntries(chartRoles.map(role => ['--chart-' + role, palette[role]]))
}
const styles = { dark: cssTokens(darkChart), light: cssTokens(lightChart) }

export function ChartSurface({ id, children, className = '' }: { id: string; children: ReactNode; className?: string }) {
  const key = 'alpha.chart-dark.v1.' + id
  const theme = useTheme()
  const pinned = useSyncExternalStore(subscribe, () => localStorage.getItem(key) === 'true', () => false)
  const mode = pinned || theme === 'dark' ? 'dark' : 'light'
  const surface = useRef<HTMLDivElement>(null)
  const [palette, setPalette] = useState<ChartPalette | null>(null)
  useLayoutEffect(() => {
    if (surface.current) setPalette(readTokens(surface.current))
  }, [mode])
  return <div className={'chart-surface ' + className} data-theme={mode} data-chart-theme={mode} style={styles[mode]} ref={surface}>
    <label className="chart-theme-control"><input type="checkbox" title="Keep this chart dark in Light and Dim" checked={pinned} onChange={event => {
      localStorage.setItem(key, String(event.target.checked))
      window.dispatchEvent(new Event(change))
    }}/>Dark chart</label>
    {(palette || typeof window === 'undefined') && <Palette.Provider value={palette ?? lightChart}>{children}</Palette.Provider>}
  </div>
}
