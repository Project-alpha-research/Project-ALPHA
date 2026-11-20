// Gates tab: every validation gate as an explained card.
//
// The inline histograms and gauges that used to live here are now the `null_distribution`
// and `confidence_intervals` figures, drawn server-side at full size with their own
// explanations. What remains is the part figures cannot carry: the gate narrative — what
// each check tests and the numbers it read. A fact check keeps a state word; a statistic shows its numbers
// and the level the old grade used, muted. Nothing here says passed or failed.

import { useMemo } from 'react'

import { gateStories } from '../../explain/gates'
import type { ValidateManifest } from '../../explain/types'
import { ExplainCard, Section } from './common'

export function Gates({ manifest }: { manifest: ValidateManifest }) {
  const stories = useMemo(() => gateStories(manifest), [manifest])
  return (
    <Section title="The five checks behind the reading">
      <div className="gate-cards">
        {stories.map((story) => (
          <ExplainCard
            key={story.gate}
            story={story}
            title={story.title}
            stats={story.stats}
            tests={story.tests}
          />
        ))}
      </div>
    </Section>
  )
}
