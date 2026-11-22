// One read per identity, with loading and plain-error states.

import { useEffect, useRef, useState } from 'react'
import { plainError } from './deskModel'

export type Load<T> = { state: 'loading' } | { state: 'ready'; value: T } | { state: 'error'; text: string }

/** One read, re-run when `key` changes; a stale answer never replaces a newer one. */
export function useLoad<T>(read: () => Promise<T>, key: string, what: string): Load<T> {
  const [result, setResult] = useState<{ key: string; load: Load<T> }>({ key, load: { state: 'loading' } })
  const latest = useRef({ read, what })
  useEffect(() => { latest.current = { read, what } })
  useEffect(() => {
    let live = true
    const { read: run, what: name } = latest.current
    run().then(
      value => { if (live) setResult({ key, load: { state: 'ready', value } }) },
      (cause: unknown) => { if (live) setResult({ key, load: { state: 'error', text: plainError(cause, name) } }) },
    )
    return () => { live = false }
  }, [key])
  return result.key === key ? result.load : { state: 'loading' }
}
