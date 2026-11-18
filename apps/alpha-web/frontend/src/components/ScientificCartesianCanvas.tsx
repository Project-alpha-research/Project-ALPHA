import { useChartPalette } from '../theme/themeState'
import { useEffect, useRef, useState } from 'react'
import type { ScientificRow, mountCartesian } from './bokehCartesian'
import { useSettings } from '../state/settings'
import { cssVars, technicalStyle } from './technical/technicalTokens'
export function ScientificCartesianCanvas({ rows, title, xLabel, yLabel, bars }: { rows: ScientificRow[]; title: string; xLabel: string; yLabel: string; bars: boolean }) {
  const palette = useChartPalette()
  const colors = useRef(palette); colors.current = palette
  const plot = useRef<Awaited<ReturnType<typeof mountCartesian>> | null>(null)
  const host = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)
  const { chartStyle } = useSettings()
  useEffect(() => {
    let live = true
    setError(null)
    import('./bokehCartesian').then(async ({ mountCartesian }) => {
      if (!live) return
      const mounted = await mountCartesian(host.current!, rows, xLabel, yLabel, bars, chartStyle, colors.current)
      if (!live) mounted.destroy()
      else { plot.current = mounted; mounted.recolor(colors.current) }
    }).catch(reason => { if (live) setError(String(reason)) })
    return () => { live = false; plot.current?.destroy(); plot.current = null }
  }, [rows, xLabel, yLabel, bars, chartStyle])
  useEffect(() => { plot.current?.recolor(palette) }, [palette])
  return <>{error ? <p role="alert">{title} unavailable: {error}</p> : null}<div ref={host} className="scientific-cartesian-host" style={cssVars(technicalStyle(chartStyle, palette)) as React.CSSProperties} role="group" aria-label={`Interactive Bokeh ${title}; ${xLabel} versus ${yLabel}. Recorded values table below.`}/></>
}
