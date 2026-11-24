import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { RecordedValuesTable } from './RecordedValuesTable'

const points = [
  { time: '2024-01-02', timestamp: '2024-01-02', date: '2024-01-02', x: 1, y: 1.5, value: 1.5 },
  { time: '2024-01-03', timestamp: '2024-01-03', date: '2024-01-03', x: 2, y: 2.5, value: 2.5 },
  { time: '2024-01-04', timestamp: '2024-01-04', date: '2024-01-04', x: 3, y: 3.5, value: 3.5 },
] as never

describe('RecordedValuesTable buttons', () => {
  it('every button of the recorded values table is type=button and never submits a form', () => {
    const onSubmit = vi.fn((event: { preventDefault: () => void }) => event.preventDefault())
    render(
      <form onSubmit={onSubmit}>
        <RecordedValuesTable points={points} label="Series" unit="USD" panelId="panel-1" />
      </form>,
    )
    const buttons = screen.queryAllByRole('button')
    expect(buttons.length).toBeGreaterThan(0)
    for (const button of buttons) {
      expect(button.getAttribute('type')).toBe('button')
      fireEvent.click(button)
    }
    expect(onSubmit).not.toHaveBeenCalled()
  })
})
