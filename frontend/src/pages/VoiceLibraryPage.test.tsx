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

describe('VoiceLibraryPage — load failure & retry', () => {
  const failingHandler = (url: string) =>
    url.endsWith('/api/voices')
      ? jsonResponse(500, { detail: 'Voice service unavailable.' })
      : jsonResponse(404, {})

  it('shows the error banner with Retry and not the empty state when the initial load fails', async () => {
    mockApi(failingHandler)
    renderPage()
    await waitFor(() =>
      expect(screen.getByText('Voice service unavailable.')).toBeInTheDocument(),
    )
    expect(screen.getByRole('alert')).toHaveTextContent('Voice service unavailable.')
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    expect(screen.queryByText(/No voices yet/)).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Create your first voice' }),
    ).not.toBeInTheDocument()
  })

  it('re-runs the load on Retry, clears the error, and renders voices on success', async () => {
    let fail = true
    let getCalls = 0
    mockApi((url) => {
      if (url.endsWith('/api/voices')) {
        getCalls++
        return fail
          ? jsonResponse(500, { detail: 'Voice service unavailable.' })
          : jsonResponse(200, [draftVoice])
      }
      return jsonResponse(404, {})
    })
    renderPage()
    const retry = await screen.findByRole('button', { name: 'Retry' })
    expect(getCalls).toBe(1)
    fail = false
    const user = userEvent.setup()
    await user.click(retry)
    await waitFor(() =>
      expect(screen.queryByText('Voice service unavailable.')).not.toBeInTheDocument(),
    )
    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Design voice' })).toBeInTheDocument(),
    )
    expect(getCalls).toBe(2)
  })

  it('shows the empty state and CTA after a successful load with zero voices', async () => {
    mockApi(emptyVoicesHandler)
    renderPage()
    await waitFor(() =>
      expect(
        screen.getByRole('button', { name: 'Create your first voice' }),
      ).toBeInTheDocument(),
    )
    expect(screen.getByText(/No voices yet/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument()
  })
})

describe('VoiceLibraryPage — modal accessibility', () => {
  const draftCardHandler = (url: string) =>
    url.endsWith('/api/voices') ? jsonResponse(200, [draftVoice]) : jsonResponse(404, {})

  it('gives NewVoiceModal an aria-labelledby pointing to its heading', async () => {
    const user = userEvent.setup()
    mockApi(emptyVoicesHandler)
    renderPage()
    await user.click(await screen.findByRole('button', { name: 'New voice' }))
    const dialog = screen.getByRole('dialog')
    const labelledBy = dialog.getAttribute('aria-labelledby')
    expect(labelledBy).toBeTruthy()
    expect(document.getElementById(String(labelledBy))).toHaveTextContent('Create & design voice')
  })

  it('closes NewVoiceModal on Escape when idle', async () => {
    const user = userEvent.setup()
    mockApi(emptyVoicesHandler)
    renderPage()
    await user.click(await screen.findByRole('button', { name: 'New voice' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('does not close NewVoiceModal on Escape while creating is in progress', async () => {
    let resolveCreate!: (resp: Response) => void
    const createPromise = new Promise<Response>((res) => {
      resolveCreate = res
    })
    mockApi((url, init) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith('/api/voices') && method === 'POST') return createPromise
      if (url.endsWith('/api/voices') && method === 'GET') return jsonResponse(200, [])
      return jsonResponse(404, {})
    })
    renderPage()
    await fillCreateForm()
    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: 'Create voice & generate preview' }))
    await user.keyboard('{Escape}')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    await act(async () => {
      resolveCreate(jsonResponse(201, draftVoice))
    })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('restores focus to the New voice trigger when the create modal closes', async () => {
    const user = userEvent.setup()
    mockApi(emptyVoicesHandler)
    renderPage()
    const trigger = await screen.findByRole('button', { name: 'New voice' })
    await user.click(trigger)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(trigger).toHaveFocus()
  })

  it('gives DesignVoiceModal an aria-labelledby pointing to its heading', async () => {
    const user = userEvent.setup()
    mockApi(draftCardHandler)
    renderPage()
    await user.click(await screen.findByRole('button', { name: 'Design voice' }))
    const dialog = screen.getByRole('dialog')
    const labelledBy = dialog.getAttribute('aria-labelledby')
    expect(labelledBy).toBeTruthy()
    expect(document.getElementById(String(labelledBy))).toHaveTextContent(
      'Design voice — Narrator',
    )
  })

  it('closes DesignVoiceModal on Escape when idle', async () => {
    const user = userEvent.setup()
    mockApi(draftCardHandler)
    renderPage()
    await user.click(await screen.findByRole('button', { name: 'Design voice' }))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('does not close DesignVoiceModal on Escape while designing is in progress', async () => {
    let resolveDesign!: (resp: Response) => void
    const designPromise = new Promise<Response>((res) => {
      resolveDesign = res
    })
    mockApi((url, init) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith('/api/voices') && method === 'GET') return jsonResponse(200, [draftVoice])
      if (url.endsWith('/api/voices/v1/design') && method === 'POST') return designPromise
      return jsonResponse(404, {})
    })
    renderPage()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Design voice' }))
    await user.type(screen.getByLabelText(/^voice description$/i), 'A calm voice')
    await user.type(screen.getByLabelText(/^reference text$/i), 'Hello world')
    await user.click(screen.getByRole('button', { name: 'Generate preview' }))
    await user.keyboard('{Escape}')
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    await act(async () => {
      resolveDesign(jsonResponse(200, { ...draftVoice, status: 'designing' }))
    })
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
  })

  it('restores focus to the Design voice trigger when the design modal closes', async () => {
    const user = userEvent.setup()
    mockApi(draftCardHandler)
    renderPage()
    const trigger = await screen.findByRole('button', { name: 'Design voice' })
    await user.click(trigger)
    expect(screen.getByRole('dialog')).toBeInTheDocument()
    await user.keyboard('{Escape}')
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument())
    expect(trigger).toHaveFocus()
  })
})

describe('VoiceLibraryPage — deletion', () => {
  const approvedVoice = {
    ...draftVoice,
    status: 'approved',
    has_approved_prompt: true,
  }

  const approveCardHandler: RouteHandler = (url, init) => {
    const method = init?.method ?? 'GET'
    if (url.endsWith('/api/voices') && method === 'GET') {
      return jsonResponse(200, [approvedVoice])
    }
    return jsonResponse(404, {})
  }

  it('warns that deleting a voice also deletes its narrations', async () => {
    const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    let deleted = false
    mockApi((url, init) => {
      const method = init?.method ?? 'GET'
      if (url.startsWith('/api/voices/') && method === 'DELETE') {
        deleted = true
        return jsonResponse(204)
      }
      return approveCardHandler(url, init)
    })
    renderPage()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Delete' }))
    expect(confirmSpy).toHaveBeenCalledWith(
      'Delete voice "Narrator"? This also deletes all narrations made with this voice and cannot be undone.',
    )
    await waitFor(() => expect(deleted).toBe(true))
    await waitFor(() =>
      expect(screen.queryByText('Narrator')).not.toBeInTheDocument(),
    )
  })

  it('does not call the API when the confirmation is dismissed', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(false)
    let deleted = false
    mockApi((url, init) => {
      const method = init?.method ?? 'GET'
      if (url.startsWith('/api/voices/') && method === 'DELETE') {
        deleted = true
        return jsonResponse(204)
      }
      return approveCardHandler(url, init)
    })
    renderPage()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Delete' }))
    await flushPromises()
    expect(deleted).toBe(false)
    expect(screen.getByText('Narrator')).toBeInTheDocument()
  })

  it('disables delete while a voice is designing', async () => {
    mockApi((url, init) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith('/api/voices') && method === 'GET') {
        return jsonResponse(200, [{ ...draftVoice, status: 'designing' }])
      }
      return jsonResponse(404, {})
    })
    renderPage()
    const deleteBtn = await screen.findByRole('button', { name: 'Delete' })
    expect(deleteBtn).toBeDisabled()
  })

  it('disables delete while a voice is approving', async () => {
    mockApi((url, init) => {
      const method = init?.method ?? 'GET'
      if (url.endsWith('/api/voices') && method === 'GET') {
        return jsonResponse(200, [{ ...draftVoice, status: 'approving' }])
      }
      return jsonResponse(404, {})
    })
    renderPage()
    const deleteBtn = await screen.findByRole('button', { name: 'Delete' })
    expect(deleteBtn).toBeDisabled()
  })

  it('surfaces a 409 as the backend error message', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true)
    mockApi((url, init) => {
      const method = init?.method ?? 'GET'
      if (url.startsWith('/api/voices/') && method === 'DELETE') {
        return jsonResponse(409, {
          detail: 'A narration or design job is still in progress.',
        })
      }
      return approveCardHandler(url, init)
    })
    renderPage()
    const user = userEvent.setup()
    await user.click(await screen.findByRole('button', { name: 'Delete' }))
    expect(
      await screen.findByText('A narration or design job is still in progress.'),
    ).toBeInTheDocument()
    expect(screen.getByText('Narrator')).toBeInTheDocument()
  })
})
