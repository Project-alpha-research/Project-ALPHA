import { ColorType } from 'lightweight-charts'
import type { ChartPalette } from '../theme/themes'

export function marketChartTheme(colors: ChartPalette) {
  const crosshairLine = { color: colors.muted, labelBackgroundColor: colors.line }
  return {
    layout: {
      background: { type: ColorType.Solid as const, color: colors.bg },
      textColor: colors.muted,
      fontFamily: 'JetBrains Mono Variable, ui-monospace, monospace',
      fontSize: 14,
      panes: { separatorColor: colors.border, separatorHoverColor: colors.link },
    },
    grid: { vertLines: { color: colors.grid }, horzLines: { color: colors.grid } },
    rightPriceScale: { borderColor: colors.line },
    timeScale: { borderColor: colors.line },
    crosshair: { vertLine: crosshairLine, horzLine: crosshairLine },
  }
}
