import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'

import { hours, ms, num, pct, relativeTime } from './format'
import { LimitBar, ResultChip, StatusChip } from './ui'

describe('ResultChip', () => {
  it('always shows a text label next to the colour (colour-blind safe)', () => {
    render(
      <>
        <ResultChip result="OK" />
        <ResultChip result="MARGINAL" />
        <ResultChip result="NOK" suspect />
      </>,
    )
    expect(screen.getByText('OK')).toBeInTheDocument()
    expect(screen.getByText('Marginal')).toBeInTheDocument()
    expect(screen.getByText('Not OK')).toBeInTheDocument()
    expect(screen.getByText('suspect')).toBeInTheDocument()
  })
})

describe('StatusChip', () => {
  it('labels NC states', () => {
    render(<StatusChip status="PENDING_VERIFICATION" />)
    expect(screen.getByText('Pending verification')).toBeInTheDocument()
  })
})

describe('LimitBar', () => {
  it('describes the value against its limits', () => {
    render(<LimitBar actual={72.034} lsl={72} usl={72.03} result="NOK" />)
    expect(screen.getByLabelText('actual 72.034 between 72 and 72.03')).toBeInTheDocument()
  })
})

describe('format helpers', () => {
  it('formats numbers, times and percentages', () => {
    expect(num('72.034')).toBe('72.034')
    expect(num(null)).toBe('-')
    expect(ms(1112)).toBe('1112 ms')
    expect(ms(12_500)).toBe('12.5 s')
    expect(pct(80)).toBe('80.0%')
    expect(pct(null)).toBe('-')
    expect(hours(6)).toBe('6.0 h')
    expect(hours(72)).toBe('3.0 d')
    const now = Date.parse('2026-11-08T10:00:00Z')
    expect(relativeTime('2026-11-08T09:58:00Z', now)).toBe('2 min ago')
    expect(relativeTime('2026-11-08T09:59:50Z', now)).toBe('just now')
  })
})
