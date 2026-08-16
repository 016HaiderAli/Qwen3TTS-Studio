import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { NarrationStudioPage } from './NarrationStudioPage'

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

const approvedVoice = {
  id: 'v1',
  name: 'Narrator',
  language: 'English',
  description: 'A calm voice',
  reference_text: 'Hello world',
  status: 'approved',
  has_approved_prompt: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

const baseNarration = {
  id: 'n1',
  voice_id: 'v1',
  title: 'My narration',
  script: 'Hello world',
  delivery_direction: '',
  language: 'English',
  status: 'queued',
  chunk_count: 3,
  chunks_done: 0,
  duration_sec: null,
  sample_rate: null,
  error: null,
  created_at: '2026-01-01T00:00:00Z',
}

function renderPage() {
  return render(
    <MemoryRouter>
      <NarrationStudioPage />
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

function submitScript() {
  fireEvent.change(screen.getByPlaceholderText(/Paste the script/), {
    target: { value: 'Hello world' },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Generate narration' }))
}

const liveRegion = () => {
  const node = document.querySelector('[aria-live="polite"]')
  expect(node).not.toBeNull()
  return node as HTMLElement
}

beforeEach(() => {
  Element.prototype.scrollIntoView = vi.fn()
})

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('NarrationStudioPage — progress & completion feedback', () => {
  it('polls and shows chunk progress while generating', async () => {
    vi.useFakeTimers()
    let getCalls = 0
    mockApi((url, init) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith('/api/voices')) return jsonResponse(200, [approvedVoice])
      if (url.endsWith('/api/narrations') && method === 'POST') {
        return jsonResponse(201, baseNarration)
      }
      if (url.endsWith('/api/narrations/n1')) {
        getCalls++
        if (getCalls === 1) {
          return jsonResponse(200, { ...baseNarration, status: 'running', chunks_done: 1 })
        }
        if (getCalls === 2) {
          return jsonResponse(200, { ...baseNarration, status: 'running', chunks_done: 3 })
        }
        return jsonResponse(200, {
          ...baseNarration,
          status: 'ready',
          chunks_done: 3,
          duration_sec: 12.5,
        })
      }
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    submitScript()
    await flushPromises()
    expect(screen.getByText(/Chunk 0 of 3/)).toBeInTheDocument()
    await advance(2000)
    expect(screen.getByText(/Chunk 1 of 3/)).toBeInTheDocument()
    await advance(2000)
    expect(screen.getByText(/Chunk 3 of 3/)).toBeInTheDocument()
    await advance(2000)
    expect(screen.getByRole('heading', { name: 'Ready' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Download WAV' })).toBeInTheDocument()
  })

  it('disables the form while a narration is generating', async () => {
    vi.useFakeTimers()
    mockApi((url, init) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith('/api/voices')) return jsonResponse(200, [approvedVoice])
      if (url.endsWith('/api/narrations') && method === 'POST') {
        return jsonResponse(201, baseNarration)
      }
      if (url.endsWith('/api/narrations/n1')) {
        return jsonResponse(200, { ...baseNarration, status: 'running' })
      }
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    submitScript()
    await flushPromises()
    expect(screen.getByPlaceholderText(/Paste the script/)).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Generating…' })).toBeDisabled()
  })

  it('announces ready and scrolls into view exactly once', async () => {
    vi.useFakeTimers()
    mockApi((url, init) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith('/api/voices')) return jsonResponse(200, [approvedVoice])
      if (url.endsWith('/api/narrations') && method === 'POST') {
        return jsonResponse(201, baseNarration)
      }
      if (url.endsWith('/api/narrations/n1')) {
        return jsonResponse(200, {
          ...baseNarration,
          status: 'ready',
          chunks_done: 3,
          duration_sec: 12.5,
        })
      }
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    submitScript()
    await flushPromises()
    expect(liveRegion()).toHaveTextContent('Generation started.')
    await advance(2000)
    await advance(2000)
    expect(liveRegion()).toHaveTextContent('Narration ready.')
    const scrollIntoView = Element.prototype.scrollIntoView as unknown as ReturnType<
      typeof vi.fn
    >
    expect(scrollIntoView).toHaveBeenCalledTimes(1)
  })

  it('announces failure and renders the error panel', async () => {
    vi.useFakeTimers()
    mockApi((url, init) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith('/api/voices')) return jsonResponse(200, [approvedVoice])
      if (url.endsWith('/api/narrations') && method === 'POST') {
        return jsonResponse(201, baseNarration)
      }
      if (url.endsWith('/api/narrations/n1')) {
        return jsonResponse(200, {
          ...baseNarration,
          status: 'failed',
          error: 'GPU worker unavailable.',
        })
      }
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    submitScript()
    await flushPromises()
    await advance(2000)
    expect(screen.getByRole('heading', { name: 'Generation failed' })).toBeInTheDocument()
    expect(screen.getByText('GPU worker unavailable.')).toBeInTheDocument()
    expect(liveRegion()).toHaveTextContent('Narration generation failed.')
  })

  it('retry re-submits and creates a new narration record', async () => {
    vi.useFakeTimers()
    let posts = 0
    mockApi((url, init) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith('/api/voices')) return jsonResponse(200, [approvedVoice])
      if (url.endsWith('/api/narrations') && method === 'POST') {
        posts++
        return jsonResponse(201, {
          ...baseNarration,
          id: posts === 1 ? 'n1' : 'n2',
        })
      }
      if (url.endsWith('/api/narrations/n1')) {
        return jsonResponse(200, { ...baseNarration, status: 'failed', error: 'boom' })
      }
      if (url.endsWith('/api/narrations/n2')) {
        return jsonResponse(200, {
          ...baseNarration,
          id: 'n2',
          status: 'running',
          chunks_done: 1,
        })
      }
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    submitScript()
    await flushPromises()
    await advance(2000)
    expect(screen.getByRole('heading', { name: 'Generation failed' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await flushPromises()
    expect(posts).toBe(2)
    expect(liveRegion()).toHaveTextContent('Generation started.')
    await advance(2000)
    expect(screen.getByText(/Chunk 1 of 3/)).toBeInTheDocument()
  })

  it('survives a transient polling rejection without crashing', async () => {
    vi.useFakeTimers()
    let getCalls = 0
    mockApi((url, init) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith('/api/voices')) return jsonResponse(200, [approvedVoice])
      if (url.endsWith('/api/narrations') && method === 'POST') {
        return jsonResponse(201, baseNarration)
      }
      if (url.endsWith('/api/narrations/n1')) {
        getCalls++
        if (getCalls === 1) {
          return Promise.reject(new TypeError('Network request failed'))
        }
        return jsonResponse(200, { ...baseNarration, status: 'running', chunks_done: 2 })
      }
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    submitScript()
    await flushPromises()
    await advance(2000)
    await advance(2000)
    expect(screen.getByText(/Chunk 2 of 3/)).toBeInTheDocument()
  })
})

describe('NarrationStudioPage — voice selection', () => {
  it('includes a voice that has an approved version even while it is being redesigned', async () => {
    const redesigning = {
      ...approvedVoice,
      status: 'designing',
    }
    mockApi((url) => {
      if (url.endsWith('/api/voices')) return jsonResponse(200, [redesigning])
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    const select = screen.getByLabelText(/^Voice$/) as HTMLSelectElement
    expect(select).toBeInTheDocument()
    expect([...select.options].map((o) => o.value)).toEqual(['v1'])
    expect(screen.getByText('Narrator (English)')).toBeInTheDocument()
  })

  it('does not offer a draft voice without an approved version', async () => {
    const draft = {
      ...approvedVoice,
      status: 'draft',
      has_approved_prompt: false,
    }
    mockApi((url) => {
      if (url.endsWith('/api/voices')) return jsonResponse(200, [draft])
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    const select = screen.getByLabelText(/^Voice$/) as HTMLSelectElement
    expect(select).toBeInTheDocument()
    expect([...select.options].map((o) => o.value)).toEqual([])
  })
})
