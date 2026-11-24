import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import { RecordedValuesTable } from './RecordedValuesTable'

const points = Array.from({ length: 30 }, (_, i) => ({
  index: i,
  x: i,
  y: 100 + i,
  t: `2024-01-${String((i % 28) + 1).padStart(2, '0')}`,
  time: `2024-01-${String((i % 28) + 1).padStart(2, '0')}`,
  timestamp: `2024-01-${String((i % 28) + 1).padStart(2, '0')}`,
  date: `2024-01-${String((i % 28) + 1).padStart(2, '0')}`,
  value: 100 + i,
})) as never

describe('RecordedValuesTable buttons', () => {
  it('every button of the recorded values table has type=button', () => {
    const html = renderToStaticMarkup(
      <form>
        <RecordedValuesTable points={points} label="Equity" unit="USD" panelId="panel-1" />
      </form>,
    )
    const buttons = html.match(/<button\b[^>]*>/g) ?? []
    expect(buttons.length).toBeGreaterThan(0)
    for (const tag of buttons) {
      expect(tag).toMatch(/\btype="button"/)
    }
  })
})
