// Gates tab: every validation gate as an explained card.
//
// Each card puts one plain sentence first, then a small chart drawn from this run's own recorded
// data (`checkChartModel.ts`, `nullChartModel.ts`), then the numbers and a closed method note.
// A chart whose data the run did not record says so in one muted line. Nothing here says passed or failed.

import { useMemo, type ReactNode } from 'react'

import { gateStories } from '../../explain/gates'
import type { ValidateManifest } from '../../explain/types'
import { ChartNote, NotAvailable } from './chartParts'
import { CpcvView, DsrView, IntervalView } from './CheckCharts'
import { ciChart, cpcvChart, dsrChart, type Chart } from './checkChartModel'
import { nullCharts, missingDraws } from './nullChartModel'
import { NullView } from './NullChart'
import { useCheckChartData } from './useCheckChartData'
import { WalkForwardView } from './WalkForward'
import { walkForwardChart } from './walkForwardModel'
import { ExplainCard, Section } from './common'

function show<T>(model: Chart<T>, view: (chart: T & { status: 'ok' }) => ReactNode): ReactNode {
  return model.status === 'ok' ? view(model) : <NotAvailable model={model} />
}

export function Gates({ manifest, runId }: { manifest: ValidateManifest; runId: string }) {
  const stories = useMemo(() => gateStories(manifest), [manifest])
  const { bars, nulls } = useCheckChartData(runId, manifest)
  const charts = useMemo<Record<string, ReactNode>>(() => {
    const loading = <ChartNote text="Loading chart…" />
    const missing = (reason: string) => <NotAvailable model={{ status: 'not-recorded', reason }} />
    const walk = bars.state === 'loading' ? loading : show(walkForwardChart(manifest, bars.state === 'ready' ? bars.value : null), (c) => <WalkForwardView chart={c} />)
    let nullNode: ReactNode = loading
    if (nulls.state !== 'loading') {
      const model = nullCharts(manifest, nulls.state === 'ready' ? nulls.value : null)
      nullNode = model.status === 'ok' ? <NullView tiers={model.tiers} skipped={model.skipped} /> : missing(model.reason || missingDraws)
    }
    return {
      walk_forward_oos: walk,
      randomized_price_null: nullNode,
      bootstrap_ci: show(ciChart(manifest), (c) => <IntervalView chart={c} />),
      deflated_sharpe: show(dsrChart(manifest), (c) => <DsrView chart={c} />),
      cpcv_oos: show(cpcvChart(manifest), (c) => <CpcvView chart={c} />),
    }
  }, [manifest, bars, nulls])
  return (
    <Section title="The five checks behind the reading">
      <div className="gate-cards">
        {stories.map((story) => (
          <ExplainCard key={story.gate} story={story} title={story.title} stats={story.stats} tests={story.tests} chart={charts[story.gate]} />
        ))}
      </div>
    </Section>
  )
}
