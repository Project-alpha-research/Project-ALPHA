// The desk's dark browser-chart surface: reads the `--chart-*` tokens from `tokens.css` and hands
// them to every chart inside, so price, equity and drawdown charts match the desk.

import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { Palette } from '../theme/themeState'
import type { ChartPalette } from '../theme/themes'
import { readTokens } from '../util/tokens'

export function DeskChartSurface({ children, className = '' }: { children: ReactNode; className?: string }) {
  const surface = useRef<HTMLDivElement>(null)
  const [palette, setPalette] = useState<ChartPalette | null>(null)
  useLayoutEffect(() => { if (surface.current) setPalette(readTokens(surface.current)) }, [])
  return <div ref={surface} className={`d-chart-surface ${className}`}>
    {palette ? <Palette.Provider value={palette}>{children}</Palette.Provider> : null}
  </div>
}
