import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { type Narration } from '../api'
import { BuiltinVoicesPage } from './BuiltinVoicesPage'

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

const queuedNarration: Narration = {
  id: 'n1',
  voice_id: null,
  voice_source: 'custom_voice',
  title: 'My narration',
  script: 'Hello studio',
  delivery_direction: '',
  language: 'English',
  status: 'queued',
  dialogue_speaker_count: 1,
  dialogue_segments: [],
  chunk_count: 2,
  chunks_done: 0,
  duration_sec: null,
  sample_rate: null,
  error: null,
  created_at: '2026-01-01T00:00:00Z',
}

function renderPage(entry = '/tts-studio') {
  return render(
    <MemoryRouter initialEntries={[entry]}>
      <BuiltinVoicesPage />
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

function fillAndSubmit(script = 'Hello studio') {
  fireEvent.change(screen.getByLabelText(/Script \*/i), {
    target: { value: script },
  })
  fireEvent.click(screen.getByRole('button', { name: 'Generate narration' }))
}

describe('BuiltinVoicesPage — generate button unlocks on job completion', () => {
  beforeEach(() => {
    vi.useFakeTimers()
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('re-enables the Generate button as soon as the job reaches a terminal state', async () => {
    // Mutable narration state: queued while generating, ready after the poll.
    let narration = { ...queuedNarration }
    mockApi((url) => {
      if (url.includes('/preview')) return jsonResponse(404, { detail: 'no preview' })
      if (url === '/api/voices' || url.startsWith('/api/voices?')) return jsonResponse(200, [])
      if (url === '/api/builtin-voices/generate') return jsonResponse(200, queuedNarration)
      if (url === '/api/narrations/n1') return jsonResponse(200, narration)
      if (url.startsWith('/api/files/')) return jsonResponse(404)
      return jsonResponse(404)
    })

    renderPage()
    await flushPromises()

    const generateBtn = () => screen.getByRole('button', { name: /generat(e|ing)/i })
    fillAndSubmit()
    await flushPromises()
    // Job queued: the button is locked while the worker processes.
    expect(generateBtn()).toBeDisabled()

    // Poll tick while still queued: stays locked.
    await advance(2000)
    expect(generateBtn()).toBeDisabled()

    // Worker finished: the very next poll unlocks the button.
    narration = { ...queuedNarration, status: 'ready', chunks_done: 2, duration_sec: 3.2 }
    await advance(2000)
    expect(screen.getByRole('button', { name: 'Generate narration' })).not.toBeDisabled()
    // The output panel shows the finished artifact and its export controls.
    expect(screen.getByRole('link', { name: 'Download WAV' })).toBeInTheDocument()
  })

  it('re-enables the button when the job fails', async () => {
    let narration = { ...queuedNarration }
    mockApi((url) => {
      if (url.includes('/preview')) return jsonResponse(404, { detail: 'no preview' })
      if (url === '/api/voices' || url.startsWith('/api/voices?')) return jsonResponse(200, [])
      if (url === '/api/builtin-voices/generate') return jsonResponse(200, queuedNarration)
      if (url === '/api/narrations/n1') return jsonResponse(200, narration)
      return jsonResponse(404)
    })

    renderPage()
    await flushPromises()

    fillAndSubmit()
    await flushPromises()
    expect(screen.getByRole('button', { name: /generating/i })).toBeDisabled()

    narration = { ...queuedNarration, status: 'failed', error: 'worker exploded' }
    await advance(2000)
    expect(screen.getByRole('button', { name: 'Generate narration' })).not.toBeDisabled()
    expect(screen.getByText('worker exploded')).toBeInTheDocument()
  })

  it('"New narration" clears script/title and resets sliders to defaults', async () => {
    let narration = { ...queuedNarration }
    mockApi((url) => {
      if (url.includes('/preview')) return jsonResponse(404, { detail: 'no preview' })
      if (url === '/api/voices' || url.startsWith('/api/voices?')) return jsonResponse(200, [])
      if (url === '/api/builtin-voices/generate') return jsonResponse(200, queuedNarration)
      if (url === '/api/narrations/n1') return jsonResponse(200, narration)
      return jsonResponse(404)
    })

    renderPage()
    await flushPromises()

    const textarea = screen.getByLabelText(/Script \*/i) as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: 'Hello studio' } })
    fireEvent.change(screen.getByLabelText(/Title/i), { target: { value: 'My title' } })
    // Nudge the sliders away from their defaults.
    const rate = screen.getByLabelText(/Speech rate:/i) as HTMLInputElement
    fireEvent.change(rate, { target: { value: '1.8' } })
    expect(rate.value).toBe('1.8')

    fillAndSubmit('Hello studio')
    await flushPromises()
    narration = { ...queuedNarration, status: 'ready', chunks_done: 2, duration_sec: 3.2 }
    await advance(2000)

    // The audio widget is visible (output panel in complete state)…
    expect(screen.getByRole('link', { name: 'Download WAV' })).toBeInTheDocument()

    // …and "New narration" returns the whole workspace to its initial state.
    fireEvent.click(screen.getByRole('button', { name: /new narration/i }))
    expect((screen.getByLabelText(/Script \*/i) as HTMLTextAreaElement).value).toBe('')
    expect((screen.getByLabelText(/Title/i) as HTMLInputElement).value).toBe('')
    expect((screen.getByLabelText(/Speech rate:/i) as HTMLInputElement).value).toBe('1')
    expect(
      screen.getByText(/Your generated narration audio will appear here/i),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Generate narration' })).not.toBeDisabled()
  })

  it('"Clear script" empties the textarea', async () => {
    mockApi((url) => {
      if (url.includes('/preview')) return jsonResponse(404, { detail: 'no preview' })
      if (url === '/api/voices' || url.startsWith('/api/voices?')) return jsonResponse(200, [])
      return jsonResponse(404)
    })

    renderPage()
    await flushPromises()

    const textarea = screen.getByLabelText(/Script \*/i) as HTMLTextAreaElement
    fireEvent.change(textarea, { target: { value: 'To be cleared' } })
    const clearBtn = screen.getByRole('button', { name: 'Clear script text' })
    expect(clearBtn).not.toBeDisabled()
    fireEvent.click(clearBtn)
    expect((screen.getByLabelText(/Script \*/i) as HTMLTextAreaElement).value).toBe('')
    expect(clearBtn).toBeDisabled()
  })
})
