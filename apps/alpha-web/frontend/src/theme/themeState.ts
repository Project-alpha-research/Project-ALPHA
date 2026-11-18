import { createContext, useContext, useSyncExternalStore } from 'react'
import { currentTheme, lightChart, subscribeTheme, type ChartPalette } from './themes'

export const Palette = createContext<ChartPalette>(lightChart)
export const useChartPalette = () => useContext(Palette)
export const useTheme = () => useSyncExternalStore(subscribeTheme, currentTheme, () => 'light' as const)
