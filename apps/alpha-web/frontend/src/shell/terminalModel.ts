import type { Profile } from '../state/settings'
import { workflowPages, type PageId } from './workflowModel'

const CODES: Record<string, string> = {
  PriceChart: 'CHART', MarketWatch: 'WATCH', DataManager: 'DATA', IdeaWorkspace: 'IDEAS',
  StrategyBuilder: 'RULES', Scanner: 'SCAN', Navigator: 'LIBRARY', AllTests: 'TESTS',
  Workspaces: 'DESKS', Governance: 'HELP', Alerts: 'ALERTS', MachineLearning: 'ML', JobMonitor: 'JOBS',
}
export function functionEntries(profile: Profile) {
  return workflowPages(profile).flatMap(page => page.panes.map(pane => ({
    code: CODES[pane.name] ?? pane.name.toUpperCase(), page: page.id as PageId,
    pane: pane.name, title: pane.title, section: page.title,
  })))
}
export function resolveFunction(value: string, profile: Profile) {
  const key = value.trim().toLowerCase()
  return functionEntries(profile).find(entry => [entry.code, entry.pane, entry.title].some(text => text.toLowerCase() === key)) ?? null
}
export interface DeskPreferences { watch: boolean; data: boolean; maximized: boolean; width: number }
export function restoreDesk(raw: unknown): DeskPreferences {
  const value = raw && typeof raw === 'object' ? raw as Record<string, unknown> : {}
  return {
    watch: typeof value.watch === 'boolean' ? value.watch : true,
    data: typeof value.data === 'boolean' ? value.data : false,
    maximized: typeof value.maximized === 'boolean' ? value.maximized : false,
    width: typeof value.width === 'number' && Number.isFinite(value.width) ? Math.max(230, Math.min(420, value.width)) : 285,
  }
}
