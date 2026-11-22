import { expect, it } from 'vitest'
import { restoreDocumentTabs } from './documentTabs'
it('validates routes, run identity and profile-specific documents on restore', () => {
  const tabs = [{ page: 'data', pane: 'FundingData', title: 'Untrusted title' }, { page: 'results', pane: 'RunDetail', runId: 'a'.repeat(16) }, { page: 'results', pane: 'RunDetail', runId: 'a'.repeat(16) }, { page: 'invalid', pane: 'Missing' }]
  expect(restoreDocumentTabs(tabs, 'equities').map(t => t.title)).toEqual(['Report'])
  expect(restoreDocumentTabs(tabs, 'crypto').map(t => t.title)).toEqual(['Report'])
  expect(restoreDocumentTabs(null, 'crypto')).toEqual([])
})
