import './ReadingBlock.css'
import type { CheckState } from '../panels/readingModel'

export function StateIcon({ state }: { state: CheckState }) {
  // Three shapes, so the state never rests on colour: a ticked circle, a triangle, a dashed circle.
  return <svg className="reading-icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true" focusable="false">
    {state === 'sound' && <><circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M5 8.3 7.2 10.5 11 5.7" fill="none" stroke="currentColor" strokeWidth="1.5" /></>}
    {state === 'fault' && <><path d="M8 1.8 14.6 13.8H1.4Z" fill="none" stroke="currentColor" strokeWidth="1.5" /><path d="M8 6v3.6M8 11.2v1" stroke="currentColor" strokeWidth="1.5" /></>}
    {state === 'not-checked' && <circle cx="8" cy="8" r="6.5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeDasharray="2.4 2.4" />}
  </svg>
}
