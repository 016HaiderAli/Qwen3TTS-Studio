import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { VoiceLibraryPage } from './VoiceLibraryPage'

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

const draftVoice = {
  id: 'v1',
  name: 'Narrator',
  language: 'English',
  description: 'A calm voice',
  reference_text: 'Hello world',
  status: 'draft',
  has_approved_prompt: false,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
}

function emptyVoicesHandler(url: string): Response {
  return url.endsWith('/api/voices') ? jsonResponse(200, []) : jsonResponse(404, {})
}

function renderPage() {
  return render(
    <MemoryRouter>
      <VoiceLibraryPage />
    </MemoryRouter>,
  )
}

async function fillCreateForm() {
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'New voice' }))
  await user.type(screen.getByLabelText(/^voice name$/i), 'Narrator')
  await user.type(screen.getByLabelText(/^voice description$/i), 'A calm voice')
  await user.type(screen.getByLabelText(/^reference text$/i), 'Hello world')
  return user
}

async function fillDesignForm() {
  const user = userEvent.setup()
  await user.click(screen.getByRole('button', { name: 'Design voice' }))
  await user.type(screen.getByLabelText(/^voice description$/i), 'A calm voice')
  await user.type(screen.getByLabelText(/^reference text$/i), 'Hello world')
  return user
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

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
})

describe('VoiceLibraryPage — create & design', () => {
  it('opens the combined modal from the New voice button', async () => {
    const user = userEvent.setup()
    const fetchMock = mockApi(emptyVoicesHandler)
    renderPage()
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    await user.click(screen.getByRole('button', { name: 'New voice' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Create & design voice' })).toBeInTheDocument()
    expect(screen.getByLabelText(/^voice name$/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/^language$/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/^voice description$/i)).toBeInTheDocument()
    expect(screen.getByLabelText(/^reference text$/i)).toBeInTheDocument()
  })

  it('shows a Create your first voice CTA in the empty state that opens the modal', async () => {
    const user = userEvent.setup()
    mockApi(emptyVoicesHandler)
    renderPage()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Create your first voice' })).toBeInTheDocument(),
    )
    await user.click(screen.getByRole('button', { name: 'Create your first voice' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })

  it('disables submit until name, description and reference text are filled', async () => {
    const user = userEvent.setup()
    const fetchMock = mockApi(emptyVoicesHandler)
    renderPage()
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    await user.click(screen.getByRole('button', { name: 'New voice' }))
    const submit = screen.getByRole('button', { name: 'Create voice & generate preview' })
    expect(submit).toBeDisabled()
    await user.type(screen.getByLabelText(/^voice name$/i), 'Narrator')
    expect(submit).toBeDisabled()
    await user.type(screen.getByLabelText(/^voice description$/i), 'A calm voice')
    expect(submit).toBeDisabled()
    await user.type(screen.getByLabelText(/^reference text$/i), 'Hello world')
    expect(submit).toBeEnabled()
  })

  it('populates fields from example chips', async () => {
    const user = userEvent.setup()
    const fetchMock = mockApi(emptyVoicesHandler)
    renderPage()
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    await user.click(screen.getByRole('button', { name: 'New voice' }))

    const descChip = 'Warm and friendly, with a calm measured pace and a gentle smile.'
    await user.click(screen.getByRole('button', { name: descChip }))
    expect((screen.getByLabelText(/^voice description$/i) as HTMLTextAreaElement).value).toBe(
      descChip,
    )

    const refChip = 'Welcome to our story. Enjoy the journey.'
    await user.click(screen.getByRole('button', { name: refChip }))
    expect((screen.getByLabelText(/^reference text$/i) as HTMLTextAreaElement).value).toBe(refChip)
  })

  it('renders live character counters', async () => {
    const user = userEvent.setup()
    const fetchMock = mockApi(emptyVoicesHandler)
    renderPage()
    await waitFor(() => expect(fetchMock).toHaveBeenCalled())
    await user.click(screen.getByRole('button', { name: 'New voice' }))
    expect(screen.getAllByText('0 / 2000')).toHaveLength(2)
    await user.type(screen.getByLabelText(/^voice description$/i), 'abc')
    expect(screen.getByText('3 / 2000')).toBeInTheDocument()
    await user.type(screen.getByLabelText(/^reference text$/i), 'abcdef')
    expect(screen.getByText('6 / 2000')).toBeInTheDocument()
  })

  it('creates the voice then starts design with the same fields', async () => {
    const calls: Array<{ url: string; body: Record<string, string> }> = []
    mockApi((url, init) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith('/api/voices') && method === 'POST') {
        calls.push({ url, body: JSON.parse(String(init?.body)) })
        return jsonResponse(201, draftVoice)
      }
      if (url.endsWith('/api/voices/v1/design') && method === 'POST') {
        calls.push({ url, body: JSON.parse(String(init?.body)) })
        return jsonResponse(200, { ...draftVoice, status: 'designing' })
      }
      if (url.endsWith('/api/voices') && method === 'GET') return jsonResponse(200, [])
      return jsonResponse(404, {})
    })
    renderPage()
    await fillCreateForm()
    await userEvent.click(screen.getByRole('button', { name: 'Create voice & generate preview' }))

    await waitFor(() => expect(calls).toHaveLength(2))
    expect(calls[0].url).toMatch(/\/api\/voices$/)
    expect(calls[0].body).toMatchObject({
      name: 'Narrator',
      language: 'English',
      description: 'A calm voice',
      reference_text: 'Hello world',
    })
    expect(calls[1].url).toMatch(/\/api\/voices\/v1\/design$/)
    expect(calls[1].body).toEqual({
      language: 'English',
      description: 'A calm voice',
      reference_text: 'Hello world',
    })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('keeps the created draft visible and surfaces an error when design fails', async () => {
    mockApi((url, init) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith('/api/voices') && method === 'POST') {
        return jsonResponse(201, draftVoice)
      }
      if (url.endsWith('/api/voices/v1/design') && method === 'POST') {
        return jsonResponse(503, { detail: 'GPU worker unavailable.' })
      }
      if (url.endsWith('/api/voices') && method === 'GET') return jsonResponse(200, [draftVoice])
      return jsonResponse(404, {})
    })
    renderPage()
    await fillCreateForm()
    await userEvent.click(screen.getByRole('button', { name: 'Create voice & generate preview' }))

    await waitFor(() => expect(screen.getByText(/GPU worker unavailable/)).toBeInTheDocument())
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Design voice' })).toBeInTheDocument(),
    )
  })

  it('renders the approval explanation on preview-ready cards', async () => {
    const previewReady = { ...draftVoice, status: 'preview_ready' }
    mockApi((url) =>
      url.endsWith('/api/voices') ? jsonResponse(200, [previewReady]) : jsonResponse(404, {}),
    )
    renderPage()
    await waitFor(() =>
      expect(screen.getByText(/Happy with this preview\?/)).toBeInTheDocument(),
    )
  })
})

describe('VoiceLibraryPage — progress & completion feedback', () => {
  const designingVoice = {
    ...draftVoice,
    status: 'designing',
    updated_at: new Date(Date.now() - 90000).toISOString(),
  }

  const designingA = { ...draftVoice, id: 'a1', name: 'Voice A', status: 'designing' }
  const designingB = { ...draftVoice, id: 'b1', name: 'Voice B', status: 'designing' }
  const draftB = { ...draftVoice, id: 'b1', name: 'Voice B', status: 'draft' }

  const liveRegion = () => {
    const node = document.querySelector('[aria-live="polite"]')
    expect(node).not.toBeNull()
    return node as HTMLElement
  }

  it('shows an indeterminate spinner and elapsed time for a designing voice', async () => {
    mockApi((url) =>
      url.endsWith('/api/voices')
        ? jsonResponse(200, [designingVoice])
        : jsonResponse(404, {}),
    )
    renderPage()
    expect(await screen.findByRole('status', { name: 'Designing voice' })).toBeInTheDocument()
    expect(screen.getByText(/elapsed/)).toBeInTheDocument()
  })

  it('announces when a voice starts designing', async () => {
    const designing = { ...draftVoice, status: 'designing' }
    mockApi((url, init) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith('/api/voices') && method === 'GET') return jsonResponse(200, [draftVoice])
      if (url.endsWith('/api/voices/v1/design') && method === 'POST') {
        return jsonResponse(200, designing)
      }
      return jsonResponse(404, {})
    })
    renderPage()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Design voice' })).toBeInTheDocument(),
    )
    await fillDesignForm()
    await userEvent.click(screen.getByRole('button', { name: 'Generate preview' }))
    await waitFor(() => expect(liveRegion()).toHaveTextContent('Designing Narrator…'))
  })

  it('announces designing to preview-ready exactly once', async () => {
    vi.useFakeTimers()
    const previewReady = { ...draftVoice, status: 'preview_ready' }
    let getCalls = 0
    mockApi((url) => {
      if (url.endsWith('/api/voices')) {
        getCalls++
        return jsonResponse(200, getCalls === 1 ? [designingVoice] : [previewReady])
      }
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    expect(liveRegion()).toHaveTextContent('')
    await advance(2000)
    expect(liveRegion()).toHaveTextContent('Narrator preview is ready.')
    expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument()
  })

  it('announces approving to approved', async () => {
    vi.useFakeTimers()
    const approving = { ...draftVoice, status: 'approving' }
    const approved = { ...draftVoice, status: 'approved' }
    let getCalls = 0
    mockApi((url) => {
      if (url.endsWith('/api/voices')) {
        getCalls++
        if (getCalls === 1) return jsonResponse(200, [approving])
        return jsonResponse(200, [approved])
      }
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    await advance(2000)
    expect(liveRegion()).toHaveTextContent('Narrator is approved and ready for narration.')
    expect(screen.getByRole('button', { name: 'Use for narration' })).toBeInTheDocument()
  })

  it('detects design failure and keeps the retry action available', async () => {
    vi.useFakeTimers()
    let getCalls = 0
    mockApi((url) => {
      if (url.endsWith('/api/voices')) {
        getCalls++
        return jsonResponse(200, getCalls === 1 ? [designingVoice] : [draftVoice])
      }
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    await advance(2000)
    expect(liveRegion()).toHaveTextContent('Design failed for Narrator.')
    expect(screen.getByRole('button', { name: 'Design voice' })).toBeInTheDocument()
  })

  it('detects approval failure and keeps the preview retry available', async () => {
    vi.useFakeTimers()
    const approving = { ...draftVoice, status: 'approving' }
    const previewReady = { ...draftVoice, status: 'preview_ready' }
    let getCalls = 0
    mockApi((url) => {
      if (url.endsWith('/api/voices')) {
        getCalls++
        return jsonResponse(200, getCalls === 1 ? [approving] : [previewReady])
      }
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    await advance(2000)
    expect(liveRegion()).toHaveTextContent(
      'Approval failed for Narrator. The preview is still available.',
    )
    expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument()
  })

  it('does not re-announce a status that already transitioned', async () => {
    vi.useFakeTimers()
    let getCalls = 0
    mockApi((url) => {
      if (url.endsWith('/api/voices')) {
        getCalls++
        let b = designingB
        if (getCalls === 2 || getCalls === 4) b = draftB
        return jsonResponse(200, [designingA, b])
      }
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    await advance(2000)
    expect(liveRegion()).toHaveTextContent('Design failed for Voice B.')
    await advance(2000)
    expect(liveRegion()).toHaveTextContent('Designing Voice B…')
    await advance(2000)
    expect(liveRegion()).toHaveTextContent('Designing Voice B…')
  })

  it('disables Approve immediately while approval is pending', async () => {
    const previewReady = { ...draftVoice, status: 'preview_ready' }
    let resolveApprove!: (resp: Response) => void
    const approvePromise = new Promise<Response>((res) => {
      resolveApprove = res
    })
    mockApi((url, init) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith('/api/voices') && method === 'GET') {
        return jsonResponse(200, [previewReady])
      }
      if (url.endsWith('/api/voices/v1/approve') && method === 'POST') {
        return approvePromise
      }
      return jsonResponse(404, {})
    })
    renderPage()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument(),
    )
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Approve' }))
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approving…' })).toBeDisabled()
    await act(async () => {
      resolveApprove(jsonResponse(200, { ...previewReady, status: 'approving' }))
    })
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Approving…' })).toBeDisabled(),
    )
  })
})

describe('VoiceLibraryPage — non-destructive redesign', () => {
  const approvedVoice = {
    ...draftVoice,
    status: 'approved',
    has_approved_prompt: true,
  }

  const liveRegion = () => {
    const node = document.querySelector('[aria-live="polite"]')
    expect(node).not.toBeNull()
    return node as HTMLElement
  }

  it('keeps the approved voice usable for narration while a redesign is in progress', async () => {
    const designing = { ...approvedVoice, status: 'designing' }
    mockApi((url) =>
      url.endsWith('/api/voices')
        ? jsonResponse(200, [designing])
        : jsonResponse(404, {}),
    )
    renderPage()

    expect(
      await screen.findByRole('button', { name: 'Use for narration' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/current approved version stays available for narration/),
    ).toBeInTheDocument()
    expect(screen.getByText(/Creating a new version of your approved voice/)).toBeInTheDocument()
  })

  it('marks the approved card as the current approved version', async () => {
    mockApi((url) =>
      url.endsWith('/api/voices')
        ? jsonResponse(200, [approvedVoice])
        : jsonResponse(404, {}),
    )
    renderPage()
    await waitFor(() =>
      expect(screen.getByText(/This is your current approved version/)).toBeInTheDocument(),
    )
    expect(screen.getByRole('button', { name: 'Use for narration' })).toBeInTheDocument()
  })

  it('announces that a redesign is generating a new version', async () => {
    const designing = { ...approvedVoice, status: 'designing' }
    mockApi((url, init) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith('/api/voices') && method === 'GET') {
        return jsonResponse(200, [approvedVoice])
      }
      if (url.endsWith('/api/voices/v1/design') && method === 'POST') {
        return jsonResponse(200, designing)
      }
      return jsonResponse(404, {})
    })
    renderPage()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Redesign' })).toBeInTheDocument(),
    )
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Redesign' }))
    expect(screen.getByRole('heading', { name: 'Redesign voice — Narrator' })).toBeInTheDocument()
    expect(
      screen.getByText(/current approved version stays available for narration/),
    ).toBeInTheDocument()
    await user.type(screen.getByLabelText(/^reference text$/i), 'New script line')
    await user.click(screen.getByRole('button', { name: 'Generate preview' }))
    await waitFor(() => expect(liveRegion()).toHaveTextContent('Generating a new version of Narrator…'))
    expect(
      screen.getByText(/Creating a new version of your approved voice/),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Use for narration' })).toBeInTheDocument()
  })

  it('explains that approving a redesigned preview replaces the current version', async () => {
    const previewReady = { ...approvedVoice, status: 'preview_ready' }
    mockApi((url) =>
      url.endsWith('/api/voices')
        ? jsonResponse(200, [previewReady])
        : jsonResponse(404, {}),
    )
    renderPage()
    await waitFor(() =>
      expect(
        screen.getByText(/replaces your current approved voice for narration/),
      ).toBeInTheDocument(),
    )
    expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument()
  })

  it('keeps the narration action available while a redesigned preview awaits approval', async () => {
    const previewReady = { ...approvedVoice, status: 'preview_ready' }
    mockApi((url) =>
      url.endsWith('/api/voices')
        ? jsonResponse(200, [previewReady])
        : jsonResponse(404, {}),
    )
    renderPage()
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Use for narration' })).toBeInTheDocument(),
    )
  })

  it('restores the approved state after a failed redesign', async () => {
    vi.useFakeTimers()
    const designing = { ...approvedVoice, status: 'designing' }
    let getCalls = 0
    mockApi((url) => {
      if (url.endsWith('/api/voices')) {
        getCalls++
        return jsonResponse(200, getCalls === 1 ? [designing] : [approvedVoice])
      }
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    await advance(2000)

    expect(
      screen.getByText(/Redesign failed for Narrator\. Your approved voice is still available\./),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Use for narration' }),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Redesign' })).toBeInTheDocument()
    expect(liveRegion()).toHaveTextContent(
      'Redesign failed for Narrator. Your approved voice is still available.',
    )
  })

  it('announces approval failure of a redesign keeping the approved version usable', async () => {
    vi.useFakeTimers()
    const approving = { ...approvedVoice, status: 'approving' }
    const previewReady = { ...approvedVoice, status: 'preview_ready' }
    let getCalls = 0
    mockApi((url) => {
      if (url.endsWith('/api/voices')) {
        getCalls++
        return jsonResponse(200, getCalls === 1 ? [approving] : [previewReady])
      }
      return jsonResponse(404, {})
    })
    renderPage()
    await flushPromises()
    await advance(2000)

    expect(liveRegion()).toHaveTextContent(
      'Approval failed for Narrator. Your approved voice is still available.',
    )
    expect(screen.getByRole('button', { name: 'Use for narration' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Approve' })).toBeInTheDocument()
  })
})
