import './CheckCharts.css'
import type { NotRecorded } from './checkChartModel'

// Small parts every check chart shares.

export function ChartNote({ text }: { text: string }) {
  return <p className="muted check-chart-missing">{text}</p>
}
export const NotAvailable = ({ model }: { model: NotRecorded }) => <ChartNote text={`Chart not available: ${model.reason}.`} />

export function Legend({ items }: { items: { cls?: string; text: string }[] }) {
  return (
    <ul className="check-chart-legend">
      {items.map((item) => (
        <li key={item.text}>{item.cls ? <span className={`check-chart-swatch ${item.cls}`} aria-hidden="true" /> : null}{item.text}</li>
      ))}
    </ul>
  )
}
