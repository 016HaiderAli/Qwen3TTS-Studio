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

describe('HistoryPage — empty state & initial-load retry', () => {
  it('shows an empty state with a Create a narration CTA linking to the studio', async () => {
    mockApi((url) =>
      url.endsWith('/api/narrations') ? jsonResponse(200, []) : jsonResponse(404, {}),
    )
    renderPage()
    await waitFor(() => expect(screen.getByText(/No narrations yet/)).toBeInTheDocument())
    expect(screen.getByRole('link', { name: 'Create a narration' })).toHaveAttribute(
      'href',
      '/narration',
    )
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument()
  })

  it('shows a Retry action on initial-load failure without the empty-state CTA', async () => {
    let calls = 0
    mockApi((url) => {
      if (url.endsWith('/api/narrations')) {
        calls++
        if (calls === 1) return jsonResponse(500, { detail: 'boom' })
        return jsonResponse(200, [readyItem])
      }
      return jsonResponse(404, {})
    })
    renderPage()
    await waitFor(() => expect(screen.getByText('boom')).toBeInTheDocument())
    expect(screen.getByRole('alert')).toHaveTextContent('boom')
    expect(screen.queryByText(/No narrations yet/)).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Create a narration' })).not.toBeInTheDocument()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() =>
      expect(screen.getByRole('link', { name: 'Download' })).toBeInTheDocument(),
    )
    expect(screen.queryByText('boom')).not.toBeInTheDocument()
    expect(calls).toBe(2)
  })
})

describe('HistoryPage — failed narration error details', () => {
  const failedItem = { ...queuedItem, status: 'failed' }
  const failedNarration = {
    id: 'n1',
    voice_id: 'v1',
    title: 'My narration',
    script: 'Hello world',
    delivery_direction: '',
    language: 'English',
    status: 'failed',
    chunk_count: 1,
    chunks_done: 0,
    duration_sec: null,
    sample_rate: null,
    error: 'GPU worker timed out.',
    created_at: '2026-01-01T00:00:00Z',
  }

  it('expands on demand, fetches the detail endpoint and shows the error inline', async () => {
    let detailCalls = 0
    mockApi((url, init) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith('/api/narrations') && method === 'GET') {
        return jsonResponse(200, [failedItem])
      }
      if (url.endsWith('/api/narrations/n1')) {
        detailCalls++
        return jsonResponse(200, failedNarration)
      }
      return jsonResponse(404, {})
    })
    renderPage()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Error details' })).toBeInTheDocument(),
    )
    const btn = screen.getByRole('button', { name: 'Error details' })
    expect(btn).toHaveAttribute('aria-expanded', 'false')
    expect(btn).toHaveAttribute('aria-controls', 'narration-error-n1')
    const user = userEvent.setup()
    await user.click(btn)
    await waitFor(() => expect(screen.getByText('GPU worker timed out.')).toBeInTheDocument())
    expect(detailCalls).toBe(1)
    expect(btn).toHaveAttribute('aria-expanded', 'true')
    expect(document.getElementById('narration-error-n1')).toHaveTextContent(
      'GPU worker timed out.',
    )
    expect(liveRegion()).not.toHaveTextContent('GPU worker timed out.')
  })

  it('collapses on a second click', async () => {
    mockApi((url, init) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith('/api/narrations') && method === 'GET') {
        return jsonResponse(200, [failedItem])
      }
      if (url.endsWith('/api/narrations/n1')) return jsonResponse(200, failedNarration)
      return jsonResponse(404, {})
    })
    renderPage()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Error details' })).toBeInTheDocument(),
    )
    const user = userEvent.setup()
    const btn = screen.getByRole('button', { name: 'Error details' })
    await user.click(btn)
    await waitFor(() => expect(screen.getByText('GPU worker timed out.')).toBeInTheDocument())
    await user.click(btn)
    await waitFor(() =>
      expect(screen.queryByText('GPU worker timed out.')).not.toBeInTheDocument(),
    )
    expect(btn).toHaveAttribute('aria-expanded', 'false')
  })

  it('does not fire duplicate detail requests on rapid repeated clicks', async () => {
    let resolveDetail: (r: Response) => void
    const detailPromise = new Promise<Response>((resolve) => {
      resolveDetail = resolve
    })
    let detailCalls = 0
    mockApi((url, init) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith('/api/narrations') && method === 'GET') {
        return jsonResponse(200, [failedItem])
      }
      if (url.endsWith('/api/narrations/n1')) {
        detailCalls++
        return detailPromise
      }
      return jsonResponse(404, {})
    })
    renderPage()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Error details' })).toBeInTheDocument(),
    )
    const user = userEvent.setup()
    const btn = screen.getByRole('button', { name: 'Error details' })
    await user.click(btn)
    await user.click(btn)
    await user.click(btn)
    resolveDetail!(jsonResponse(200, failedNarration))
    await flushPromises()
    expect(detailCalls).toBe(1)
    await waitFor(() => expect(screen.getByText('GPU worker timed out.')).toBeInTheDocument())
  })

  it('handles a failure while loading error details gracefully', async () => {
    mockApi((url, init) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith('/api/narrations') && method === 'GET') {
        return jsonResponse(200, [failedItem])
      }
      if (url.endsWith('/api/narrations/n1')) {
        return jsonResponse(500, { detail: 'Detail fetch failed.' })
      }
      return jsonResponse(404, {})
    })
    renderPage()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Error details' })).toBeInTheDocument(),
    )
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Error details' }))
    await waitFor(() => expect(screen.getByText('Detail fetch failed.')).toBeInTheDocument())
  })
})

describe('HistoryPage — regression', () => {
  it('keeps ready-row playback, download and reuse intact', async () => {
    mockApi((url) =>
      url.endsWith('/api/narrations') ? jsonResponse(200, [readyItem]) : jsonResponse(404, {}),
    )
    renderPage()
    await waitFor(() =>
      expect(screen.getByRole('link', { name: 'Download' })).toBeInTheDocument(),
    )
    expect(
      screen.getByRole('group', { name: 'Audio player: My narration' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Reuse in studio' })).toHaveAttribute(
      'href',
      '/narration?reuse=n1&voice=v1',
    )
    expect(screen.queryByRole('button', { name: 'Error details' })).not.toBeInTheDocument()
  })

  it('keeps failed-row reuse intact without a detail panel until requested', async () => {
    const failedItem = { ...queuedItem, status: 'failed' }
    mockApi((url) =>
      url.endsWith('/api/narrations') ? jsonResponse(200, [failedItem]) : jsonResponse(404, {}),
    )
    renderPage()
    await waitFor(() =>
      expect(screen.getByRole('link', { name: 'Reuse in studio' })).toBeInTheDocument(),
    )
    expect(screen.getByRole('button', { name: 'Error details' })).toBeInTheDocument()
    expect(screen.queryByText('GPU worker timed out.')).not.toBeInTheDocument()
  })
})
