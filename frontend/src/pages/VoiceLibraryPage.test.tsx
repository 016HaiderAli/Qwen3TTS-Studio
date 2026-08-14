import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { VoiceLibraryPage } from './VoiceLibraryPage'

function jsonResponse(status: number, body?: unknown) {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

type RouteHandler = (url: string, init?: RequestInit) => Response

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

afterEach(() => {
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
