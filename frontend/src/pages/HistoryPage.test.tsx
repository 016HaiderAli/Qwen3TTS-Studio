import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { HistoryPage } from './HistoryPage'

function jsonResponse(status: number, body?: unknown) {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

type RouteHandler = (url: string, init?: RequestInit) => Response | Promise<Response>

function mockApi(handler: RouteHandler) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation((url, init) =>
    Promise.resolve(handler(String(url), init)),
  )
}

const queuedItem = {
  id: 'n1',
  title: 'My narration',
  voice_id: 'v1',
  voice_name: 'Narrator',
  status: 'queued',
  duration_sec: null,
  created_at: new Date(Date.now() - 5000).toISOString(),
}

const readyItem = {
  ...queuedItem,
  status: 'ready',
  duration_sec: 12.5,
}

function renderPage() {
  return render(
    <MemoryRouter>
      <HistoryPage />
    </MemoryRouter>,
  )
}

const flushPromises = async () => {
  await act(async () => {
    for (let i = 0; i < 5; i++) await Promise.resolve()
  })
}

const advance = async (ms: number) => {
  await act(async () => {
    vi.advanceTimersByTime(ms)
  })
  await flushPromises()
}

const liveRegion = () => {
  const node = document.querySelector('[aria-live="polite"]')
  expect(node).not.toBeNull()
  return node as HTMLElement
}

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('HistoryPage — progress & completion feedback', () => {
  it('polls and updates rows when a narration becomes ready', async () => {
    vi.useFakeTimers()
    let getCalls = 0
    mockApi((url, init) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith('/api/narrations') && method === 'GET') {
        getCalls++
        return jsonResponse(200, getCalls === 1 ? [queuedItem] : [readyItem])
      }
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    expect(screen.getByText('Queued')).toBeInTheDocument()
    expect(screen.getByText(/elapsed/)).toBeInTheDocument()
    await advance(2000)
    expect(screen.getByText('Ready')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Download' })).toBeInTheDocument()
    expect(liveRegion()).toHaveTextContent('Narration "My narration" is ready.')
  })

  it('does not announce narrations already in a terminal state on first load', async () => {
    mockApi((url) =>
      url.endsWith('/api/narrations') ? jsonResponse(200, [readyItem]) : jsonResponse(404, {}),
    )
    renderPage()
    await waitFor(() => expect(screen.getByText('Ready')).toBeInTheDocument())
    expect(liveRegion()).toHaveTextContent('')
  })

  it('does not re-announce a ready narration on later polls', async () => {
    vi.useFakeTimers()
    const queuedOther = { ...queuedItem, id: 'n2', title: 'Other narration' }
    let getCalls = 0
    mockApi((url) => {
      if (url.endsWith('/api/narrations')) {
        getCalls++
        if (getCalls === 1) return jsonResponse(200, [queuedItem, queuedOther])
        return jsonResponse(200, [readyItem, queuedOther])
      }
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    await advance(2000)
    expect(liveRegion()).toHaveTextContent('Narration "My narration" is ready.')
    await advance(2000)
    await advance(2000)
    expect(liveRegion()).toHaveTextContent('Narration "My narration" is ready.')
  })

  it('deletes a narration while preserving playback and download', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    let deleted = false
    mockApi((url, init) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith('/api/narrations') && method === 'GET') {
        return jsonResponse(200, [readyItem])
      }
      if (url.endsWith('/api/narrations/n1') && method === 'DELETE') {
        deleted = true
        return jsonResponse(204)
      }
      return jsonResponse(404, {})
    })
    renderPage()
    await waitFor(() => expect(screen.getByRole('link', { name: 'Download' })).toBeInTheDocument())
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Delete' }))
    expect(deleted).toBe(true)
    await waitFor(() => expect(screen.queryByText('My narration')).not.toBeInTheDocument())
  })
})

describe('HistoryPage — reuse in studio', () => {
  it('links ready narrations to the studio with reuse and voice params', async () => {
    mockApi((url) =>
      url.endsWith('/api/narrations') ? jsonResponse(200, [readyItem]) : jsonResponse(404, {}),
    )
    renderPage()
    await waitFor(() => expect(screen.getByRole('link', { name: 'Reuse in studio' })).toBeInTheDocument())
    expect(screen.getByRole('link', { name: 'Reuse in studio' })).toHaveAttribute(
      'href',
      '/narration?reuse=n1&voice=v1',
    )
  })

  it('also offers reuse for failed narrations', async () => {
    const failedItem = { ...queuedItem, status: 'failed' }
    mockApi((url) =>
      url.endsWith('/api/narrations') ? jsonResponse(200, [failedItem]) : jsonResponse(404, {}),
    )
    renderPage()
    await waitFor(() => expect(screen.getByRole('link', { name: 'Reuse in studio' })).toBeInTheDocument())
    expect(screen.getByRole('link', { name: 'Reuse in studio' })).toHaveAttribute(
      'href',
      '/narration?reuse=n1&voice=v1',
    )
  })
})
