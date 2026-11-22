// Home ("Today"): the market now, the paper book, and the last ten stored tests.

import { FollowToday } from '../panels/FollowToday'
import { MarketOverview } from '../panels/MarketOverview'
import { readRecentRuns } from './deskApi'
import { Empty, Panel, Problem, Skeleton } from './parts'
import { useLoad } from './useLoad'
import { RunsTable } from './RunsTable'

export function RecentTests({ onOpen, onAll }: { onOpen(runId: string): void; onAll(): void }) {
  const load = useLoad(() => readRecentRuns(10), 'recent', 'the recent tests')
  return <Panel title="Recent tests" className="d-home-tests"
    aside={<button type="button" className="d-btn d-btn-quiet" onClick={onAll}>All tests</button>}>
    {load.state === 'loading' ? <Skeleton rows={6} height={22} label="Loading the recent tests" />
      : load.state === 'error' ? <Problem>{load.text}</Problem>
      : load.value.items.length ? <RunsTable rows={load.value.items} onOpen={onOpen} sortable={false} caption="The last ten stored tests, newest first" />
      : <Empty>No tests are stored yet. Ask Claude to test an idea; the run appears here when it finishes.</Empty>}
  </Panel>
}

export function HomePage({ onOpenRun, onAllTests }: { onOpenRun(runId: string): void; onAllTests(): void }) {
  return <div className="d-home">
    <RecentTests onOpen={onOpenRun} onAll={onAllTests} />
    <Panel title="Market now" className="d-home-market"><div className="d-legacy"><MarketOverview /></div></Panel>
    <Panel title="My book" className="d-home-book"><div className="d-legacy"><FollowToday /></div></Panel>
  </div>
}
