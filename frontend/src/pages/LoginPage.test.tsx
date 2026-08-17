import { describe, expect, it, vi, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { LoginPage } from './LoginPage'

afterEach(() => {
  vi.restoreAllMocks()
})

describe('LoginPage', () => {
  it('redirects to the Google authorization URL', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ url: 'https://accounts.google.com/…' }), {
          status: 200,
        }),
      ),
    )
    const location = { ...window.location }
    vi.spyOn(window, 'location', 'get').mockReturnValue({
      ...location,
      href: '',
    } as unknown as Location)

    render(<LoginPage />)
    await userEvent.click(screen.getByRole('button', { name: /continue with google/i }))

    await waitFor(() => {
      expect(window.location.href).toContain('accounts.google.com')
    })
  })

  it('shows an error when Google sign-in is not configured', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ detail: 'Google authentication is not configured.' }), {
          status: 503,
        }),
      ),
    )

    render(<LoginPage />)
    await userEvent.click(screen.getByRole('button', { name: /continue with google/i }))

    await waitFor(() => {
      expect(screen.getByText(/Google authentication is not configured/)).toBeInTheDocument()
    })
    expect(screen.getByRole('alert')).toHaveTextContent(/Google authentication is not configured/)
  })
})
