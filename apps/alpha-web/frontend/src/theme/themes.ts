export const themeNames = ['light', 'dim', 'dark'] as const
type Theme = typeof themeNames[number]
const key = 'alpha.theme.v1'
const change = 'alpha-theme-change'

function themeName(value: string | null | undefined): Theme {
  return value === 'dark' || value === 'dim' ? value : 'light'
}

export function currentTheme(): Theme {
  return themeName(document.documentElement.dataset.theme)
}

export function chooseTheme(value: string) {
  const theme = themeName(value)
  localStorage.setItem(key, theme)
  document.documentElement.dataset.theme = theme
  window.dispatchEvent(new Event(change))
}

export function subscribeTheme(listener: () => void) {
  function sync(event: StorageEvent) {
    if (event.key === key || event.key === null) {
      document.documentElement.dataset.theme = themeName(localStorage.getItem(key))
      listener()
    }
  }
  window.addEventListener('storage', sync)
  window.addEventListener(change, listener)
  return () => {
    window.removeEventListener('storage', sync)
    window.removeEventListener(change, listener)
  }
}

// Browser charts share one light surface in Light and Dim. The dark surface
// preserves the recorded terminal palette and its stable study identities.
export const darkChart = {
  bg: '#000000', ink: '#e0e0e0', dim: '#c8c8c8', muted: '#c8c8c8', grid: '#2a2a2a',
  line: '#e0e0e0', accent: '#316ac5', up: '#2fc36a', down: '#e5484d', gold: '#ffd400',
  link: '#5584cf', negative: '#e64d52', orange: '#e9a35d', purple: '#d68ee6', teal: '#55c5c5',
  border: '#767676', threshold: '#707070', volumeUp: '#2e4a38', volumeUpEdge: '#3f6a50',
  volumeDown: '#5a2f33', volumeDownEdge: '#7a3f44', classicHist: '#58a8d0', defaultHist: '#93bcb7',
}

export type ChartPalette = typeof darkChart
export const lightChart: ChartPalette = {
  bg: '#fffefa', ink: '#182327', dim: '#344a50', muted: '#4b595e', grid: '#d5dcd9',
  line: '#465559', accent: '#005b86', up: '#00614c', down: '#923f1e', gold: '#765200',
  link: '#005b86', negative: '#923f1e', orange: '#765200', purple: '#714282', teal: '#00636e',
  border: '#717d80', threshold: '#687675', volumeUp: '#bbd5cb', volumeUpEdge: '#567868',
  volumeDown: '#e4c5b7', volumeDownEdge: '#865c49', classicHist: '#81b4cb', defaultHist: '#a4c6c1',
}
