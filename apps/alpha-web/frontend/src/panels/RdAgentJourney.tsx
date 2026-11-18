import { useEffect, useState } from 'react'
import { getJSON } from '../api/client'
import type { components } from '../api/generated'
import './RdAgentJourney.css'

type Schema = components['schemas']
export type Journey = Schema['StoredJourney']
type Idea = Schema['JourneyIdea']
type JourneyRead = Journey | Schema['JourneyMissing']
const missing = 'not recorded'

function CodeExcerpt({ code }: { code: string }) {
  const lines = code.split('\n')
  return <>
    <pre><code>{lines.slice(0, 12).join('\n')}</code></pre>
    {lines.length > 12 && <details><summary>Show remaining code</summary>
      <pre><code>{lines.slice(12).join('\n')}</code></pre>
    </details>}
  </>
}

function StoredFigure({ url, title }: { url: string; title: string }) {
  const [failed, setFailed] = useState(false)
  if (failed) return <p role="alert">The stored figure could not be read.</p>
  return <figure className="figure-card journey-image" data-theme="light">
    <img className="figure-image" src={url} alt={`Stored figure for ${title}`} onError={() => setFailed(true)} />
  </figure>
}

export function RdAgentJourney({ journey, base }: { journey: Journey; base: string }) {
  // The writer ends the seventh step's facts with the judge's exploratory label.
  const facts = journey.steps[6]?.facts ?? []
  return <article className="rdagent-journey">
    <header><h2>One idea's journey: {journey.name}</h2><p className="journey-disclaimer">{facts.at(-1) || missing}</p></header>
    {journey.steps.map((step, i) => <section key={i} className="journey-step">
      <div>
        <h3>{i + 1}. {step.title || missing}</h3>
        <span className={`journey-who ${step.who?.startsWith('RD-Agent') ? 'journey-who-ai' : 'journey-who-rule'}`}>{step.who || missing}</span>
        <p>{step.text || missing}</p>
        {i === 1 && <CodeExcerpt code={step.code || missing} />}
        {!!step.numbers?.length && <dl className="journey-numbers">
          {step.numbers.slice(0, 3).map((number, index) => <div key={index}>
            <dt>{number.label || missing}</dt>
            <dd><strong>{number.display || missing}</strong><span className="journey-gloss">{number.gloss || missing}</span></dd>
          </div>)}
        </dl>}
        <p>{step.what_this_means || missing}</p>
        {i === 6 && facts.length > 1 && <ul>{facts.slice(0, -1).map((fact, n) => <li key={n}>{fact}</li>)}</ul>}
        {(step.own_words != null || i === 0 || i === 5) && <details><summary>Show the agent's own words</summary>
          <p>{step.own_words || missing}</p></details>}
        <details><summary>Where this comes from</summary>
          {step.source?.length ? <ul>{step.source.map((file, n) => <li key={n}>{file}</li>)}</ul> : <p>{missing}</p>}
        </details>
      </div>
      {step.figure ? <StoredFigure url={`${base}/figures/${encodeURIComponent(step.figure)}`} title={step.title || missing} />
        : step.figure_reason ? <p className="muted journey-reason">{step.figure_reason}</p> : null}
    </section>)}
  </article>
}

export function MissingJourney({ idea, result }: { idea: Idea; result: Schema['JourneyMissing'] }) {
  return <section><h2>{idea.name}</h2><p>{result.reason}</p>
    {idea.iteration === null && <p>A judged evaluation is not recorded for this idea. This command builds the recorded evaluations in the run.</p>}
    <code>{result.command}</code>
  </section>
}

function SelectedJourney({ base, idea }: { base: string; idea: Idea }) {
  const [result, setResult] = useState<JourneyRead | null>(null)
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let live = true
    getJSON<JourneyRead>(base).then(value => {
      if (live) setResult(value)
    }).catch((cause: unknown) => { if (live) setError(String(cause)) })
    return () => { live = false }
  }, [base])
  if (error) return <p role="alert">{error}</p>
  if (!result) return <p role="status">Loading journey…</p>
  if ('command' in result) return <MissingJourney idea={idea} result={result} />
  return <RdAgentJourney journey={result} base={base} />
}

export function JourneyPicker({ runId, ideas }: { runId: string; ideas: Idea[] }) {
  const [selected, setSelected] = useState(ideas[0]?.id)
  if (!ideas.length) return <p>Ideas: not recorded</p>
  const current = ideas.find(idea => idea.id === selected)
  return <>
    <label>Idea <select value={selected} onChange={event => setSelected(event.target.value)}>
      {ideas.map(idea => <option key={idea.id} value={idea.id}>
        {idea.name}{idea.iteration != null && ` · iteration ${idea.iteration}`} · {idea.verdict ?? missing} · {idea.built ? 'journey available' : 'journey not built yet'}
      </option>)}
    </select></label>
    {current && <SelectedJourney key={current.id} idea={current}
      base={`/api/rdagent/runs/${encodeURIComponent(runId)}/journeys/${encodeURIComponent(current.id)}`} />}
  </>
}
