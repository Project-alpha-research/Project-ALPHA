import { useMemo, useState } from 'react'

import { confirmReservedPeriod, reservedConfirmationRequest } from './ownerAuth'

function readRequest() {
  try {
    return { request: reservedConfirmationRequest(window.location.hash), error: null }
  } catch (reason) {
    return { request: null, error: reason instanceof Error ? reason.message : String(reason) }
  }
}

function periodLine(name: string, part: unknown): string {
  if (!part || typeof part !== 'object') return `${name}: not shown.`
  const item = part as Record<string, unknown>
  const sharpe = typeof item.oos_sharpe === 'number' ? item.oos_sharpe.toFixed(3) : 'not computed'
  return `${name}: Sharpe ${sharpe}. ${String(item.sentence ?? '')}`
}

export function ReservedConfirmation() {
  const parsed = useMemo(readRequest, [])
  const [busy, setBusy] = useState(false)
  const [lines, setLines] = useState<string[] | null>(null)
  const [error, setError] = useState<string | null>(parsed.error)
  const request = parsed.request

  async function confirm(): Promise<void> {
    if (!request) return
    setBusy(true)
    setError(null)
    try {
      const done = await confirmReservedPeriod(request)
      window.history.replaceState(null, '', '/owner-auth/confirm')
      const result = (done.result ?? {}) as Record<string, unknown>
      setLines([
        `Slot ${String(result.slot)} of 10 used; ${String(result.slots_left)} left.`,
        periodLine('Earlier period (seen before)', result.earlier),
        periodLine('Reserved period (seen now, once)', result.reserved),
        'This is a reading, not a verdict. It is no advice and no promise of profit.',
      ])
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason))
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="owner-enrollment-shell">
      <section className="owner-enrollment-card" aria-labelledby="reserved-confirmation-title">
        <span className="eyebrow">Project ALPHA · local owner ceremony</span>
        <h1 id="reserved-confirmation-title">Confirm one idea on the reserved period</h1>
        <p>
          The reserved period is the data from 2024-01-01 on. No test has used it. Your Touch ID
          here spends one of the 10 slots for it, once, and cannot be undone.
        </p>
        {request ? (
          <>
            <p>{request.summary}</p>
            <p>Run: {String(request.payload.run_id)}. Reserved bars up to {String(request.payload.reserved_end).slice(0, 10)}.</p>
          </>
        ) : (
          <div className="workbench-notice" role="alert">
            <strong>TRUSTED CLI REQUIRED</strong>
            <span>Run alpha confirm plan, then alpha confirm request, to get a link for 60 seconds.</span>
          </div>
        )}
        {lines ? (
          <div className="workbench-notice" role="status">
            <strong>RECORDED</strong>
            {lines.map((line) => <span key={line}>{line}</span>)}
          </div>
        ) : null}
        {error ? (
          <div className="workbench-notice" role="alert">
            <strong>NOT CONFIRMED</strong>
            <span>{error} If the link expired, run alpha confirm request again; nothing was spent.</span>
          </div>
        ) : null}
        <button
          className="btn primary"
          type="button"
          disabled={!request || busy || lines !== null}
          onClick={() => void confirm()}
        >
          {busy ? 'waiting for Touch ID…' : lines ? 'Confirmed' : 'Confirm with Touch ID'}
        </button>
        <a href="/">Return to Workstation</a>
      </section>
    </main>
  )
}
