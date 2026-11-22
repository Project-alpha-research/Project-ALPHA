// Status bar: the market shown, the UTC clock and the hovered bar from the chart. Relays only.

import { useChartHover } from '../context/chartHover'
import { useNow } from '../context/clock'
import { useSettings } from '../state/settings'
import { statusSegments } from './statusBarModel'

export function StatusBar() {
  const { profile } = useSettings()
  const hover = useChartHover()
  const now = useNow()
  const segments = statusSegments({ profile, now, hovered: hover.bar, barsLoaded: hover.barsLoaded })

  return (
    <footer className="statusbar" aria-label="Status bar">
      {segments.map((segment) => (
        <span
          key={segment.id}
          className={`status-segment status-segment--${segment.id} tone-${segment.tone}`}
          title={segment.title}
        >
          {segment.text}
        </span>
      ))}
    </footer>
  )
}
