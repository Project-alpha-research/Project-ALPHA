// Small shared desk parts: line icons, skeletons, empty and error states, sparkline.

import type { ReactNode } from 'react'
import { sparkPath, sparkTone } from './deskModel'

const PATHS: Record<string, string> = {
  home: 'M3 10.5 12 3l9 7.5V20a1 1 0 0 1-1 1h-5v-6h-6v6H4a1 1 0 0 1-1-1z',
  charts: 'M4 20V4M4 20h16M8 16v-5M12 16V8M16 16v-3M20 16V6',
  ideas: 'M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.4 1 1.1 1 1.9V16h5v-.2c0-.8.4-1.5 1-1.9A6 6 0 0 0 12 3z',
  tests: 'M9 3h6M10 3v6L4.5 19a1.5 1.5 0 0 0 1.3 2h12.4a1.5 1.5 0 0 0 1.3-2L14 9V3M7 15h10',
  setup: 'M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0M14 4v4M8 10v4M16 16v4',
  rdagent: 'M12 3v3M12 18v3M3 12h3M18 12h3M7 7l-2-2M19 19l-2-2M17 7l2-2M5 19l2-2M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8z',
  system: 'M4 5h16v10H4zM9 19h6M12 15v4',
  search: 'M11 4a7 7 0 1 0 0 14 7 7 0 0 0 0-14zM20 20l-4-4',
  close: 'M6 6l12 12M18 6 6 18',
  left: 'M15 5l-7 7 7 7',
  right: 'M9 5l7 7-7 7',
  expand: 'M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5',
}

export function Icon({ name, size = 18 }: { name: keyof typeof PATHS | string; size?: number }) {
  return <svg className="d-icon" width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
    <path d={PATHS[name] ?? ''} fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
}

export function Skeleton({ rows = 3, height = 14, label }: { rows?: number; height?: number; label: string }) {
  return <div className="d-skeleton" role="status" aria-label={label}>
    {Array.from({ length: rows }, (_, index) => <span key={index} style={{ height, width: `${92 - (index % 3) * 14}%` }} />)}
  </div>
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="d-empty">{children}</p>
}

export function Problem({ children }: { children: ReactNode }) {
  return <p className="d-problem" role="alert">{children}</p>
}

export function Panel({ title, aside, children, className = '' }: { title: string; aside?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`d-panel ${className}`} aria-label={title}>
    <header className="d-panel-head"><h2>{title}</h2>{aside ? <div className="d-panel-aside">{aside}</div> : null}</header>
    <div className="d-panel-body">{children}</div>
  </section>
}

export function Sparkline({ values, width = 96, height = 24 }: { values: readonly number[]; width?: number; height?: number }) {
  const path = sparkPath(values, width, height, 2)
  if (!path) return <span className="d-muted" aria-label="No equity curve stored">—</span>
  return <svg className={`d-spark ${sparkTone(values)}`} width={width} height={height} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Equity curve">
    <path d={path} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
  </svg>
}
