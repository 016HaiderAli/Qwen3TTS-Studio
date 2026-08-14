import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StatusBadge } from './StatusBadge'

describe('StatusBadge', () => {
  it('renders a friendly label for known statuses', () => {
    render(<StatusBadge status="preview_ready" />)
    expect(screen.getByText('Preview ready')).toBeInTheDocument()
  })

  it('renders the approving label', () => {
    render(<StatusBadge status="approving" />)
    expect(screen.getByText('Approving…')).toBeInTheDocument()
  })

  it('falls back to the raw status for unknown values', () => {
    render(<StatusBadge status="weird" />)
    expect(screen.getByText('weird')).toBeInTheDocument()
  })
})
