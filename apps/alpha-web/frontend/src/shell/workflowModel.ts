import { createElement } from 'react'
import { openRunDetail } from '../panels/actions'
import { Workspaces } from '../panels/Workspaces'
import { DOCUMENTS, documentOf, type DocumentPane } from './documents'
import { showsWindow, type WindowId } from './profiles'
import type { Profile } from '../state/settings'
import { DataManager } from '../panels/DataManager'
import { MarketWatch } from '../panels/MarketWatch'
import { MarketOverview } from '../panels/MarketOverview'
import { FollowToday } from '../panels/FollowToday'
import { Navigator } from '../panels/Navigator'
import { Alerts } from '../panels/Alerts'
import { DataPulls } from '../panels/JobMonitor'
import { AllTests } from '../panels/RecentTests'

function RunLibrary() { return createElement(Navigator, { onOpenRun: openRunDetail }) }

export const PAGE_IDS = ['overview', 'data', 'research', 'strategies', 'results', 'operations', 'settings'] as const
export type PageId = typeof PAGE_IDS[number]
export interface WorkflowPage { id: PageId; title: string; description: string; panes: DocumentPane[] }

const DOCUMENT_PAGE: Record<WindowId, PageId> = {
  chart: 'data', report: 'results', compare: 'results', builder: 'strategies', scanner: 'strategies',
  rdagent: 'research', ideas: 'research', 'setup-lab': 'research', governance: 'settings', forecast: 'results',
  jobs: 'operations',
}

export function workflowPages(profile: Profile): WorkflowPage[] {
  const pages: WorkflowPage[] = [
    { id: 'overview', title: 'Overview', description: 'Recent tests, what is followed today and the market.', panes: [] },
    { id: 'data', title: 'Data & Assets', description: 'Find assets, explore charts and prepare reliable data.', panes: [
      { name: 'DataManager', title: 'Data downloads', component: DataManager },
      { name: 'MarketWatch', title: 'Watchlist', component: MarketWatch },
      { name: 'MarketOverview', title: 'Market', component: MarketOverview },
    ] },
    { id: 'research', title: 'Research', description: 'Ideas, setups, RD-Agent runs and what is followed today.', panes: [] },
    { id: 'strategies', title: 'Strategies & Tests', description: 'Build rules and scan stored data.', panes: [] },
    { id: 'results', title: 'Results', description: 'Review stored tests, compare runs and open reports.', panes: [
      { name: 'AllTests', title: 'All tests', component: AllTests },
      { name: 'Navigator', title: 'Run library', component: RunLibrary },
    ] },
    { id: 'operations', title: 'Operations', description: 'Track jobs and alerts.', panes: [] },
    { id: 'settings', title: 'Settings', description: 'Display preferences, owner authentication and research safeguards.', panes: [{ name: 'Workspaces', title: 'Saved workspaces', component: Workspaces }] },
  ]
  for (const doc of DOCUMENTS) {
    if (!showsWindow(profile, doc.id)) continue
    const page = pages.find(item => item.id === DOCUMENT_PAGE[doc.id])!
    for (const pane of doc.panes) {
      if (!page.panes.some(item => item.name === pane.name)) page.panes.push(pane)
    }
  }
  pages.find(page => page.id === 'research')!.panes.push({ name: 'FollowToday', title: 'Today', component: FollowToday })
  pages.find(page => page.id === 'operations')!.panes.push(
    { name: 'DataPulls', title: 'Data jobs', component: DataPulls },
    { name: 'Alerts', title: 'Alerts', component: Alerts },
  )
  return pages
}

export function documentRoute(id: WindowId): { page: PageId; pane: string } {
  return { page: DOCUMENT_PAGE[id], pane: documentOf(id).panes[0].name }
}

export function workflowHash(page: PageId, pane?: string, runId?: string): string {
  const params = new URLSearchParams({ page })
  if (pane) params.set('pane', pane)
  if (runId) params.set('run', runId)
  return `#${params}`
}

export function resolveWorkflow(hash: string, profile: Profile): { page: PageId; pane: string | null; runId: string | null } {
  const params = new URLSearchParams(hash.replace(/^#/, ''))
  const candidate = params.get('run')
  const runId = candidate && /^[0-9a-f]{16}$/.test(candidate) ? candidate : null
  const pages = workflowPages(profile)
  const page = pages.find(item => item.id === (params.get('page') ?? (runId ? 'results' : 'overview'))) ?? pages[0]
  const pane = page.panes.find(item => item.name === (params.get('pane') ?? (runId ? 'RunDetail' : '')))?.name ?? page.panes[0]?.name ?? null
  return { page: page.id, pane, runId }
}
