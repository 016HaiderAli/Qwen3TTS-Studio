import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { Spinner } from './Spinner'

describe('Spinner', () => {
  it('renders an accessible indeterminate status indicator', () => {
    render(<Spinner label="Designing voice" />)
    const spinner = screen.getByRole('status', { name: 'Designing voice' })
    expect(spinner).toBeInTheDocument()
    expect(spinner).toHaveAttribute('aria-label', 'Designing voice')
    expect(spinner).toHaveClass('spinner')
  })

  it('reports the provided label', () => {
    render(<Spinner label="Approving voice" />)
    expect(screen.getByRole('status', { name: 'Approving voice' })).toBeInTheDocument()
  })
})
