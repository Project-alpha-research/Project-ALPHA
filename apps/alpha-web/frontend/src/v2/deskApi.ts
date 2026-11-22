// The desk's own reads: recent tests with a sparkline, and the status facts.

import { getJSON } from '../api/client'
import type { components } from '../api/generated'

export type DeskRunList = components['schemas']['DeskRunList']

export function readRecentRuns(limit: number, spark = true): Promise<DeskRunList> {
  return getJSON(`/api/desk/runs?limit=${limit}&spark=${spark}`)
}

export function readDeskStatus(): Promise<components['schemas']['DeskStatus']> {
  return getJSON('/api/desk/status')
}
