// Activity Feed — the desk tape: every run landing in the store and every job lifecycle change,
// live, regardless of origin (UI, CLI, Claude via MCP). Click a run event to open it.


import { Placeholder } from '../components/Placeholder'
import { AREA_TEXT, useActivity, type ActivityEvent, type ConnectionState } from '../state/activity'
import { fmtTime, shortId } from '../util/format'
import { openRunDetail } from './actions'
import { runWord } from './readingModel'
import type { PanelHandleProps } from '../context/panelHandle'

const EVENT_LABEL: Record<ActivityEvent['type'], string> = {
  run_added: 'RUN',
  run_updated: 'UPD',
  job_started: 'JOB',
  job_done: 'END',
  job_failed: 'ERR',
  job_cancelled: 'CXL',
  store_changed: 'DSK',
}

function RunWord({ run }: { run: NonNullable<ActivityEvent['run']> }) {
  const word = runWord(run.evidence, run.verdict)
  return word ? <span className={word.old ? 'muted' : undefined}>{word.text}</span> : null
}

function eventTone(t: ActivityEvent['type']): string {
  if (t === 'run_added') return 'good'
  if (t === 'job_failed') return 'bad'
  if (t === 'job_cancelled') return 'warn'
  return 'info'
}

export function ActivityFeed(_props: PanelHandleProps) {
  const { feed, connection } = useActivity()
  return <ActivityFeedView feed={feed} connection={connection} />
}

/** The feed itself. A run shows its evidence word, muted for an old grade; never a grade or a gate result. */
export function ActivityFeedView({ feed, connection }: { feed: ActivityEvent[]; connection: ConnectionState }) {
  return (
    <div className="panel">
      <div className="panel-toolbar">
        <span className="title">Activity</span>
        <span className={`chip ${connection === 'live' ? 'pass' : 'fail'}`}>{connection}</span>
        <span className="muted">everything hitting the store — UI, CLI, or Claude via MCP</span>
      </div>
      <div className="panel-body">
        {feed.length === 0 ? (
          <Placeholder big="quiet desk">
            Launch something — from the Strategy Lab, a terminal (<code>alpha validate SPY</code>),
            or Claude over MCP — and it appears here live.
          </Placeholder>
        ) : (
          <div className="feed">
            {feed.map((e) => (
              <button
                key={e.seq}
                className={`feed-row tone-${eventTone(e.type)}`}
                onClick={() => e.run && openRunDetail(e.run.run_id)}
                disabled={!e.run}
              >
                <span className="feed-time num">{fmtTime(e.at).slice(11)}</span>
                <span className={`feed-tag mono t-${eventTone(e.type)}`}>{EVENT_LABEL[e.type]}</span>
                {e.run ? (
                  <>
                    <span className="mono">{shortId(e.run.run_id)}</span>
                    <span className="chip kind">{e.run.kind}</span>
                    <span className="mono">{e.run.label ?? ''}</span>
                    <RunWord run={e.run} />
                  </>
                ) : e.job ? (
                  <span className="mono feed-cmd">{e.job.command}</span>
                ) : e.area ? (
                  <span className="mono feed-cmd">{AREA_TEXT[e.area]}</span>
                ) : null}
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
