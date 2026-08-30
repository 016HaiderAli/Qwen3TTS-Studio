import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import App from './App'

function jsonResponse(status: number, body?: unknown) {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

type RouteHandler = (url: string, init?: RequestInit) => Response | Promise<Response>

function mockFetch(handler: RouteHandler) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation((url, init) =>
    Promise.resolve(handler(String(url), init)),
  )
}

const me = { id: 'u1', email: 'alice@example.com', name: 'Alice' }

function renderApp(initialEntries: string[] = ['/voices']) {
  return render(
    <MemoryRouter initialEntries={initialEntries}>
      <App />
    </MemoryRouter>,
  )
}

afterEach(() => {
  vi.restoreAllMocks()
})

describe('App — session handling', () => {
  it('shows the login screen when the initial sign-in check returns 401', async () => {
    mockFetch((url) =>
      url.endsWith('/api/me') ? jsonResponse(401, {}) : jsonResponse(404, {}),
    )
    renderApp()
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /continue with google/i }),
      ).toBeInTheDocument(),
    )
  })

  it.each([401, 403])(
    'clears the current user and shows login when a mid-session request returns %s',
    async (status) => {
      mockFetch((url) => {
        if (url.endsWith('/api/me')) return jsonResponse(200, me)
        if (url.endsWith('/api/voices')) return jsonResponse(status, {})
        return jsonResponse(404, {})
      })
      renderApp(['/voices'])
      await waitFor(() => expect(screen.getByRole('button', { name: /alice/i })).toBeInTheDocument())
      await waitFor(() =>
        expect(
          screen.getByRole('button', { name: /continue with google/i }),
        ).toBeInTheDocument(),
      )
    },
  )

  it('clears the local session even when the logout request fails', async () => {
    mockFetch((url, init) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith('/api/me')) return jsonResponse(200, me)
      if (url.endsWith('/api/voices')) return jsonResponse(200, [])
      if (url.endsWith('/auth/logout') && method === 'POST') {
        return Promise.reject(new TypeError('Network request failed'))
      }
      return jsonResponse(404, {})
    })
    renderApp(['/voices'])
    await waitFor(() => expect(screen.getByRole('button', { name: /alice/i })).toBeInTheDocument())
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /alice/i }))
    await waitFor(() => expect(screen.getByRole('button', { name: /log out/i })).toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: /log out/i }))
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: /continue with google/i }),
      ).toBeInTheDocument(),
    )
  })
})
