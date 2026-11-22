import { formatTime } from '../util/formatTime'
// Status bar: `For Help, press F1` · market · UTC date-time · hovered OHLCV · bars loaded.
// Pure: the clock is injected, a missing hovered bar reads `—`, and a non-finite price throws
// rather than printing a number.

import type { Candle } from '../api/types'
import type { Profile } from '../state/settings'
import { profile as manifest } from './profiles'

export interface StatusSegment {
  id: 'help' | 'profile' | 'clock' | 'ohlc' | 'bars'
  text: string
  tone: 'none' | 'ok' | 'warn'
  title?: string
}

export interface StatusBarInput {
  profile: Profile
  /** Milliseconds since the epoch, injected by the caller. */
  now: number
  hovered: Candle | null
  barsLoaded: number
}

/** `1 Sep 2026, 14:02 UTC`. */
export function utcClock(now: number): string {
  const date = new Date(now)
  if (Number.isNaN(date.getTime())) throw new Error('status bar clock: invalid time')
  return formatTime(date.toISOString())
}

function price(value: number): string {
  if (!Number.isFinite(value)) throw new Error('status bar: non-finite price in hovered bar')
  return value.toLocaleString('en-US', { maximumFractionDigits: 6 })
}

export function hoveredText(bar: Candle | null): string {
  if (bar === null) return 'O: — H: — L: — C: — V: —'
  return `O: ${price(bar.o)} H: ${price(bar.h)} L: ${price(bar.l)} C: ${price(bar.c)} V: ${price(bar.v)}`
}

export function barsText(loaded: number): string {
  const text = loaded.toLocaleString('en-US')
  return `${text} / ${text} bars`
}

export function statusSegments(input: StatusBarInput): StatusSegment[] {
  return [
    { id: 'help', text: 'For Help, press F1', tone: 'none' },
    { id: 'profile', text: `Market: ${manifest(input.profile).label}`, tone: 'none' },
    { id: 'clock', text: utcClock(input.now), tone: 'none', title: new Date(input.now).toISOString() },
    { id: 'ohlc', text: hoveredText(input.hovered), tone: 'none' },
    { id: 'bars', text: barsText(input.barsLoaded), tone: 'none' },
  ]
}
