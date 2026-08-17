import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { createMemoryRouter, MemoryRouter, RouterProvider } from 'react-router-dom'
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

function renderPage(entry = '/narration') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
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
    expect(screen.getByText(/Waiting for the GPU worker/)).toBeInTheDocument()
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
    expect([...select.options].map((o) => o.value)).toEqual([''])
  })
})

describe('NarrationStudioPage — voice auto-selection & preselect', () => {
  const draftFirst = {
    ...approvedVoice,
    id: 'd1',
    name: 'Draft first',
    status: 'draft',
    has_approved_prompt: false,
  }
  const approvedA = { ...approvedVoice, id: 'a1', name: 'Voice A' }
  const approvedB = { ...approvedVoice, id: 'b1', name: 'Voice B' }

  it('auto-selects the first approved voice when none is preselected', async () => {
    mockApi((url) => {
      if (url.endsWith('/api/voices')) return jsonResponse(200, [draftFirst, approvedA])
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    expect((screen.getByLabelText(/^Voice$/) as HTMLSelectElement).value).toBe('a1')
  })

  it('falls back to the first approved voice when ?voice= is invalid or a draft', async () => {
    mockApi((url) => {
      if (url.endsWith('/api/voices')) return jsonResponse(200, [approvedA, approvedB])
      return jsonResponse(404, {})
    })
    renderPage('/narration?voice=d1')
    await flushPromises()
    expect((screen.getByLabelText(/^Voice$/) as HTMLSelectElement).value).toBe('a1')
  })

  it('updates the selected voice when the ?voice= param changes while mounted', async () => {
    mockApi((url) => {
      if (url.endsWith('/api/voices')) return jsonResponse(200, [approvedA, approvedB])
      return jsonResponse(404, {})
    })
    const router = createMemoryRouter(
      [{ path: '/narration', element: <NarrationStudioPage /> }],
      { initialEntries: ['/narration?voice=a1'] },
    )
    render(<RouterProvider router={router} />)
    await flushPromises()
    expect((screen.getByLabelText(/^Voice$/) as HTMLSelectElement).value).toBe('a1')
    await act(async () => {
      router.navigate('/narration?voice=b1')
    })
    await flushPromises()
    expect((screen.getByLabelText(/^Voice$/) as HTMLSelectElement).value).toBe('b1')
  })

  it('synchronizes the narration language to the selected voice until manually overridden', async () => {
    const chineseVoice = { ...approvedVoice, id: 'c1', name: 'Voice C', language: 'Chinese' }
    mockApi((url) => {
      if (url.endsWith('/api/voices')) return jsonResponse(200, [approvedVoice, chineseVoice])
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    expect((screen.getByLabelText(/^Voice$/) as HTMLSelectElement).value).toBe('v1')
    expect((screen.getByLabelText(/^Language$/) as HTMLSelectElement).value).toBe('English')

    fireEvent.change(screen.getByLabelText(/^Voice$/), { target: { value: 'c1' } })
    expect((screen.getByLabelText(/^Language$/) as HTMLSelectElement).value).toBe('Chinese')

    fireEvent.change(screen.getByLabelText(/^Language$/), { target: { value: 'French' } })
    fireEvent.change(screen.getByLabelText(/^Voice$/), { target: { value: 'v1' } })
    expect((screen.getByLabelText(/^Language$/) as HTMLSelectElement).value).toBe('French')
  })
})

describe('NarrationStudioPage — selected voice context panel', () => {
  it('shows name, language, description, status and reference audio for an approved voice', async () => {
    mockApi((url) => {
      if (url.endsWith('/api/voices')) return jsonResponse(200, [approvedVoice])
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    expect(screen.getByRole('heading', { name: 'Selected voice' })).toBeInTheDocument()
    expect(screen.getByText(/Narrator · English/)).toBeInTheDocument()
    expect(screen.getByText(/A calm voice/)).toBeInTheDocument()
    expect(screen.getByText('Approved')).toBeInTheDocument()
    expect(
      screen.getByRole('group', { name: 'Audio player: Narrator current approved voice' }),
    ).toBeInTheDocument()
  })

  it('marks a redesigning voice as the current approved voice without new spec details', async () => {
    const redesigning = {
      ...approvedVoice,
      status: 'designing',
      description: 'New candidate description',
      reference_text: 'New candidate reference',
    }
    mockApi((url) => {
      if (url.endsWith('/api/voices')) return jsonResponse(200, [redesigning])
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    expect(
      screen.getByText(/current approved voice\. It stays usable for narration/),
    ).toBeInTheDocument()
    expect(screen.getByText('Designing…')).toBeInTheDocument()
    expect(screen.queryByText(/New candidate description/)).not.toBeInTheDocument()
    expect(screen.queryByText(/New candidate reference/)).not.toBeInTheDocument()
  })

  it('shows the no-approved-voices empty state with a link to the library', async () => {
    const draft = { ...approvedVoice, status: 'draft', has_approved_prompt: false }
    mockApi((url) => {
      if (url.endsWith('/api/voices')) return jsonResponse(200, [draft])
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    expect(
      screen.getByRole('heading', { name: 'No approved voices yet' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Go to voice library' })).toHaveAttribute(
      'href',
      '/voices',
    )
  })
})

describe('NarrationStudioPage — script stats & estimate', () => {
  it('shows live character and word counts for the script', async () => {
    mockApi((url) => {
      if (url.endsWith('/api/voices')) return jsonResponse(200, [approvedVoice])
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    const textarea = screen.getByLabelText(/^Script$/)
    expect(screen.getByText(/0 \/ 100,000 characters/)).toBeInTheDocument()
    expect(screen.getByText(/· 0 words/)).toBeInTheDocument()

    fireEvent.change(textarea, { target: { value: 'Hello world, this is a test.' } })
    expect(screen.getByText(/28 \/ 100,000 characters/)).toBeInTheDocument()
    expect(screen.getByText(/· 6 words/)).toBeInTheDocument()
  })

  it('shows a clearly labeled approximate duration estimate before generation', async () => {
    mockApi((url) => {
      if (url.endsWith('/api/voices')) return jsonResponse(200, [approvedVoice])
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    const textarea = screen.getByLabelText(/^Script$/)
    fireEvent.change(textarea, {
      target: {
        value:
          'word word word word word word word word word word word word word word word ' +
          'word word word word word word word word word word word word word word word ' +
          'word word word word word word word word word word word word word word word',
      },
    })
    expect(screen.getByText(/~18s estimated at ~150 words\/min/)).toBeInTheDocument()
  })

  it('hides the estimate once a narration exists', async () => {
    mockApi((url, init) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith('/api/voices')) return jsonResponse(200, [approvedVoice])
      if (url.endsWith('/api/narrations') && method === 'POST') {
        return jsonResponse(201, baseNarration)
      }
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    const textarea = screen.getByLabelText(/^Script$/)
    fireEvent.change(textarea, { target: { value: 'word word word word word word' } })
    expect(screen.getByText(/estimated at ~150 words\/min/)).toBeInTheDocument()
    submitScript()
    await flushPromises()
    expect(screen.queryByText(/estimated at ~150 words\/min/)).not.toBeInTheDocument()
    expect(screen.getByText(/Waiting for the GPU worker/)).toBeInTheDocument()
  })
})

describe('NarrationStudioPage — reuse from history', () => {
  const reusable = {
    ...baseNarration,
    title: 'Reused narration',
    script: 'Reused script body.',
    delivery_direction: 'Speak slowly.',
    language: 'Chinese',
    status: 'ready' as const,
  }

  it('prefills title, script, delivery, language and voice from the reused narration', async () => {
    mockApi((url) => {
      if (url.endsWith('/api/voices')) return jsonResponse(200, [approvedVoice])
      if (url.endsWith('/api/narrations/n1')) return jsonResponse(200, reusable)
      return jsonResponse(404, {})
    })
    renderPage('/narration?reuse=n1&voice=v1')
    await flushPromises()

    expect((screen.getByLabelText(/^Title$/) as HTMLInputElement).value).toBe('Reused narration')
    expect((screen.getByLabelText(/^Script$/) as HTMLTextAreaElement).value).toBe(
      'Reused script body.',
    )
    expect((screen.getByLabelText(/^Delivery /) as HTMLTextAreaElement).value).toBe(
      'Speak slowly.',
    )
    expect((screen.getByLabelText(/^Language$/) as HTMLSelectElement).value).toBe('Chinese')
    expect((screen.getByLabelText(/^Voice$/) as HTMLSelectElement).value).toBe('v1')
  })

  it('surfaces an error and falls back when the reused narration cannot be loaded', async () => {
    mockApi((url) => {
      if (url.endsWith('/api/voices')) return jsonResponse(200, [approvedVoice])
      if (url.endsWith('/api/narrations/n1')) return jsonResponse(404, {})
      return jsonResponse(404, {})
    })
    renderPage('/narration?reuse=n1&voice=v1')
    await flushPromises()
    expect(screen.getByText('Narration not found.')).toBeInTheDocument()
    expect((screen.getByLabelText(/^Voice$/) as HTMLSelectElement).value).toBe('v1')
  })
})

describe('NarrationStudioPage — voice-list load failure & retry', () => {
  it('shows a load-error banner with Retry and not the no-approved-voices state on voice-list failure', async () => {
    let calls = 0
    mockApi((url) => {
      if (url.endsWith('/api/voices')) {
        calls++
        return jsonResponse(500, { detail: 'Voice service unavailable.' })
      }
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    expect(screen.getByText('Voice service unavailable.')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Voice service unavailable.')
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    expect(
      screen.queryByRole('heading', { name: 'No approved voices yet' }),
    ).not.toBeInTheDocument()
    expect(screen.queryByText('No approved voices yet')).not.toBeInTheDocument()
    expect(calls).toBe(1)
  })

  it('re-runs the voice load on Retry and populates the voice select on success', async () => {
    let calls = 0
    mockApi((url) => {
      if (url.endsWith('/api/voices')) {
        calls++
        return calls === 1
          ? jsonResponse(500, { detail: 'Voice service unavailable.' })
          : jsonResponse(200, [approvedVoice])
      }
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await flushPromises()
    expect(screen.queryByText('Voice service unavailable.')).not.toBeInTheDocument()
    expect((screen.getByLabelText(/^Voice$/) as HTMLSelectElement).value).toBe('v1')
    expect(calls).toBe(2)
  })

  it('shows the no-approved-voices state only after a successful load with zero usable voices', async () => {
    const draft = { ...approvedVoice, status: 'draft', has_approved_prompt: false }
    mockApi((url) => {
      if (url.endsWith('/api/voices')) return jsonResponse(200, [draft])
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    expect(
      screen.getByRole('heading', { name: 'No approved voices yet' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Go to voice library' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument()
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
