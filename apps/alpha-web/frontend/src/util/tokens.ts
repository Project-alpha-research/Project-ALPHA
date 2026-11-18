import { darkChart, type ChartPalette } from '../theme/themes'

// The unmounted/Node fallback remains a mirror of the immutable terminal figure.
export const FALLBACK = { ...darkChart, font: '11px Verdana, Tahoma, "DejaVu Sans", sans-serif' }

export function withAlpha(color: string, alpha: number): string {
  const match = /^#([0-9a-f]{6})$/i.exec(color)
  if (!match) return color
  return color + Math.round(alpha * 255).toString(16).padStart(2, '0')
}

export const chartRoles = Object.keys(darkChart) as (keyof ChartPalette)[]

/** Canvas libraries need resolved colours from this particular chart's surface. */
export function readTokens(surface: Element): ChartPalette {
  const styles = getComputedStyle(surface)
  const palette = { ...darkChart }
  for (const role of chartRoles) {
    const value = styles.getPropertyValue('--chart-' + role).trim()
    if (!value) throw new Error('Missing chart token ' + role)
    palette[role] = value
  }
  return palette
}
