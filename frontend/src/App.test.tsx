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

describe('App — workspace navigation shell (Phase 8a)', () => {
  const approvedClone = {
    id: 'cv1',
    name: 'Senku',
    language: 'English',
    description: '',
    reference_text: '',
    status: 'approved',
    has_approved_prompt: true,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  }

  const reuseNarration = {
    id: 'n1',
    voice_id: 'cv1',
    title: 'Reused',
    script: 'Hello world',
    delivery_direction: '',
    language: 'English',
    status: 'ready',
    dialogue_speaker_count: 1,
    dialogue_segments: [],
    chunk_count: 1,
    chunks_done: 1,
    duration_sec: 2,
    sample_rate: 24000,
    error: null,
    created_at: '2026-01-01T00:00:00Z',
  }

  function navFetch(url: string) {
    if (url.endsWith('/api/me')) return jsonResponse(200, me)
    if (url.endsWith('/api/voices')) return jsonResponse(200, [approvedClone])
    if (url.includes('/preview')) return jsonResponse(404, {})
    if (url.endsWith('/api/narrations/n1')) return jsonResponse(200, reuseNarration)
    return jsonResponse(404, {})
  }

  function navEntry(name: string) {
    return screen.getByRole('link', { name })
  }

  it('renders the workspace sidebar only when authenticated', async () => {
    mockFetch((url) =>
      url.endsWith('/api/me') ? jsonResponse(401, {}) : jsonResponse(404, {}),
    )
    renderApp()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /continue with google/i })).toBeInTheDocument(),
    )
    // Unauthenticated: no sidebar, no topbar.
    expect(screen.queryByRole('navigation', { name: 'Workspace navigation' })).not.toBeInTheDocument()

    mockFetch(navFetch)
    renderApp(['/voices'])
    await waitFor(() =>
      expect(screen.getByRole('navigation', { name: 'Workspace navigation' })).toBeInTheDocument(),
    )
  })

  it('exposes the simplified workspace navigation tree with correct targets', async () => {
    mockFetch(navFetch)
    renderApp(['/voices'])
    await waitFor(() => expect(navEntry('Voice Design')).toBeInTheDocument())

    expect(navEntry('Voice Design').getAttribute('href')).toBe('/voices')
    expect(navEntry('Voice Cloning').getAttribute('href')).toBe('/voices?action=clone')
    expect(navEntry('TTS Studio').getAttribute('href')).toBe('/tts-studio')
    // Phase 8a simplification: mode sub-items and the /narration entry are
    // removed from the sidebar — mode toggling lives inside the TTS Studio
    // page header, and /narration stays reachable as a deep link only.
    expect(screen.queryByRole('link', { name: 'Single Voice' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Multi-Speech' })).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Cloned Voice Studio' })).not.toBeInTheDocument()
  })

  it('activates TTS Studio on /tts-studio and on /narration', async () => {
    mockFetch(navFetch)
    const first = renderApp(['/tts-studio'])
    await waitFor(() => expect(navEntry('TTS Studio')).toBeInTheDocument())
    expect(navEntry('TTS Studio').getAttribute('aria-current')).toBe('page')
    first.unmount()

    renderApp(['/narration'])
    await waitFor(() => expect(navEntry('TTS Studio')).toBeInTheDocument())
    expect(navEntry('TTS Studio').getAttribute('aria-current')).toBe('page')
  })

  it('deactivates Voice Design while the Voice Cloning modal query is active', async () => {
    mockFetch(navFetch)
    const first = renderApp(['/voices'])
    await waitFor(() => expect(navEntry('Voice Design')).toBeInTheDocument())
    expect(navEntry('Voice Design').getAttribute('aria-current')).toBe('page')
    expect(navEntry('Voice Cloning').getAttribute('aria-current')).toBeNull()
    first.unmount()

    renderApp(['/voices?action=clone'])
    await waitFor(() => expect(navEntry('Voice Cloning')).toBeInTheDocument())
    expect(navEntry('Voice Cloning').getAttribute('aria-current')).toBe('page')
    expect(navEntry('Voice Design').getAttribute('aria-current')).toBeNull()
  })

  it('renders the brand title exactly once — inside the sidebar only', async () => {
    mockFetch(navFetch)
    renderApp(['/voices'])
    await waitFor(() => expect(navEntry('Voice Design')).toBeInTheDocument())

    // The sidebar brand is present…
    expect(screen.getByText('Voice Studio')).toBeInTheDocument()
    // …and the topbar has no second brand link ("Voice Studio" link was
    // removed from the topbar; only the sidebar renders the brand).
    expect(screen.queryByRole('link', { name: /voice studio/i })).not.toBeInTheDocument()
    // The account badge still lives in the topbar.
    expect(screen.getByRole('button', { name: /alice/i })).toBeInTheDocument()
  })

  it('collapses the sidebar to icon-only mode and persists the preference', async () => {
    const user = userEvent.setup()
    mockFetch(navFetch)
    renderApp(['/voices'])
    await waitFor(() => expect(navEntry('Voice Design')).toBeInTheDocument())

    const aside = screen.getByRole('complementary', { name: 'Voice Studio workspace' })
    expect(aside).not.toHaveClass('collapsed')
    // Labels visible while expanded.
    expect(screen.getByText('Voice Design')).toBeInTheDocument()

    const toggle = screen.getByRole('button', { name: 'Collapse sidebar' })
    await user.click(toggle)
    expect(aside).toHaveClass('collapsed')
    expect(window.localStorage.getItem('voice-studio.sidebar.collapsed')).toBe('1')
    // Icon-only: text labels are removed from the DOM; tooltips (title
    // attributes) carry the names.
    expect(screen.queryByText('Voice Design')).not.toBeInTheDocument()
    expect(navEntry('Voice Design').getAttribute('title')).toBe('Voice Design')

    await user.click(screen.getByRole('button', { name: 'Expand sidebar' }))
    expect(aside).not.toHaveClass('collapsed')
    expect(window.localStorage.getItem('voice-studio.sidebar.collapsed')).toBe('0')
    expect(screen.getByText('Voice Design')).toBeInTheDocument()
  })

  it('keeps the /narration?voice= and ?reuse= deep link contracts intact', async () => {
    mockFetch(navFetch)
    renderApp(['/narration?reuse=n1'])
    await waitFor(() =>
      expect((screen.getByLabelText('Script') as HTMLTextAreaElement).value).toBe('Hello world'),
    )
  })

  it('opens the Voice Cloning modal from ?action=clone and cleans the query on close', async () => {
    const user = userEvent.setup()
    mockFetch(navFetch)
    renderApp(['/voices?action=clone'])
    await waitFor(() =>
      expect(screen.getByRole('dialog', { name: /clone a voice/i })).toBeInTheDocument(),
    )

    // Sidebar reflects the cloning entry while the modal is open.
    expect(navEntry('Voice Cloning').getAttribute('aria-current')).toBe('page')

    await user.click(screen.getByRole('button', { name: 'Close voice cloning' }))
    await waitFor(() =>
      expect(screen.queryByRole('dialog', { name: /clone a voice/i })).not.toBeInTheDocument(),
    )
    // Query cleaned up: the cloning entry is no longer active.
    expect(navEntry('Voice Cloning').getAttribute('aria-current')).toBeNull()
  })
})
