import { createElement } from 'react'

/** Display only: preserve raw timestamps in titles and exports. Date-only ISO means midnight UTC. */
export function formatTime(iso: string): string {
  const match = /^(\d{4}-\d{2}-\d{2})(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))?$/.exec(iso)
  const date = new Date(iso)
  const day = match?.[1]
  if (!day || !Number.isFinite(date.getTime()) || new Date(`${day}T00:00:00Z`).toISOString().slice(0, 10) !== day) {
    throw new Error(`invalid ISO time: ${iso}`)
  }
  const months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']
  const clock = date.toISOString().slice(11, 16)
  return `${date.getUTCDate()} ${months[date.getUTCMonth()]} ${date.getUTCFullYear()}, ${clock} UTC`
}

/** Recorded minutes, rounded down to whole minutes; never imply that a short step took zero time. */
export function formatDuration(minutes: number): string {
  if (!Number.isFinite(minutes) || minutes < 0) throw new Error('invalid duration')
  if (minutes < 1) return '<1 min'
  const whole = Math.floor(minutes)
  const hours = Math.floor(whole / 60)
  const remainder = whole % 60
  return hours ? `${hours} h${remainder ? ` ${remainder} min` : ''}` : `${whole} min`
}

/** A shared display element keeps the exact ISO value available on hover. Numbers are Unix seconds. */
export function Timestamp({ value }: { value: string | number | null | undefined }) {
  if (value === null || value === undefined || value === '') return '—'
  const iso = typeof value === 'number' ? new Date(value * 1000).toISOString() : value
  let text = iso
  try {
    text = formatTime(iso)
  } catch {
    // Not a recognised ISO time: show it as received rather than break the panel.
  }
  return createElement('time', { title: iso }, text)
}
