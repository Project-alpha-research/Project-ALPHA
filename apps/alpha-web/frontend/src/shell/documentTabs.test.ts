import { expect, it } from 'vitest'
import { restoreDocumentTabs } from './documentTabs'
it('validates routes, run identity and profile-specific documents on restore', () => {
  const tabs = [{ page: 'data', pane: 'FundingData', title: 'Untrusted title' }, { page: 'results', pane: 'RunDetail', runId: 'a'.repeat(16) }, { page: 'results', pane: 'RunDetail', runId: 'a'.repeat(16) }, { page: 'invalid', pane: 'Missing' }]
  expect(restoreDocumentTabs(tabs, 'equities').map(t => t.title)).toEqual(['Report'])
  expect(restoreDocumentTabs(tabs, 'crypto').map(t => t.title)).toEqual(['Report'])
  expect(restoreDocumentTabs(null, 'crypto')).toEqual([])
})
it('drops saved tabs of the removed Builder, Scanner and Alerts windows without an error', () => {
  const stale = [{ page: 'strategies', pane: 'StrategyBuilder' }, { page: 'strategies', pane: 'Scanner' }, { page: 'operations', pane: 'Alerts' }, { page: 'results', pane: 'RunDetail', runId: 'a'.repeat(16) }]
  expect(restoreDocumentTabs(stale, 'crypto').map(t => t.title)).toEqual(['Report'])
})
it('drops saved tabs of the removed Governance, Saved workspaces, Watchlist and Risk windows without an error', () => {
  const stale = [{ page: 'settings', pane: 'Governance' }, { page: 'settings', pane: 'Workspaces' }, { page: 'data', pane: 'MarketWatch' }, { page: 'results', pane: 'RiskMonitor' }, { page: 'results', pane: 'RunDetail', runId: 'a'.repeat(16) }]
  expect(restoreDocumentTabs(stale, 'crypto').map(t => t.title)).toEqual(['Report'])
  expect(restoreDocumentTabs(stale, 'equities').map(t => t.title)).toEqual(['Report'])
})
