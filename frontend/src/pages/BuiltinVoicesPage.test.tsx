import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { BuiltinVoicesPage } from './BuiltinVoicesPage'

function jsonResponse(status: number, body?: unknown) {
  return new Response(status === 204 ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  })
}

function mockApi(handler: (url: string, init?: RequestInit) => Response | Promise<Response>) {
  return vi.spyOn(globalThis, 'fetch').mockImplementation((url, init) =>
    Promise.resolve(handler(String(url), init)),
  )
}

const baseNarration = {
  id: 'n1',
  voice_id: null,
  voice_source: 'custom_voice',
  title: 'Built-in: Vivian',
  script: 'Hello world',
  delivery_direction: '',
  language: 'English',
  status: 'queued',
  dialogue_speaker_count: 1,
  dialogue_segments: [],
  chunk_count: 1,
  chunks_done: 0,
  duration_sec: null,
  sample_rate: null,
  error: null,
  created_at: '2026-01-01T00:00:00Z',
}

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/builtin']}>
      <BuiltinVoicesPage />
    </MemoryRouter>,
  )
}

const flushPromises = async () => {
  await act(async () => {
    for (let i = 0; i < 5; i++) await Promise.resolve()
  })
}

describe('BuiltinVoicesPage — Phase 7B controls', () => {
  beforeEach(() => {
    mockApi((url) => {
      if (url.endsWith('/api/voices')) return jsonResponse(200, [])
      if (url.endsWith('/api/builtin-voices/generate')) {
        return jsonResponse(201, baseNarration)
      }
      return jsonResponse(404, { detail: 'no route' })
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders Speech Rate, Pitch Shift and Volume Gain sliders', async () => {
    renderPage()
    await flushPromises()
    expect(screen.getByRole('slider', { name: /speech rate/i })).toBeInTheDocument()
    expect(screen.getByRole('slider', { name: /pitch shift/i })).toBeInTheDocument()
    expect(screen.getByRole('slider', { name: /volume gain/i })).toBeInTheDocument()
  })

  it('renders all seven emotion preset chips and defaults to Neutral', async () => {
    renderPage()
    await flushPromises()
    const group = screen.getByRole('group', { name: 'Emotion presets' })
    for (const label of ['Neutral', 'Happy', 'Sad', 'Angry', 'Calm', 'Fierce', 'Whisper']) {
      expect(
        within(group).getByRole('button', { name: label }),
      ).toBeInTheDocument()
    }
    const neutral = within(group).getByRole('button', { name: 'Neutral' })
    expect(neutral).toHaveAttribute('aria-pressed', 'true')
  })

  it('submits voice_setting (speed/pitch/vol/emotion) and delivery_instruction', async () => {
    const fetchSpy = mockApi((url) => {
      if (url.endsWith('/api/voices')) return jsonResponse(200, [])
      if (url.endsWith('/api/builtin-voices/generate')) {
        return jsonResponse(201, baseNarration)
      }
      return jsonResponse(404, { detail: 'no route' })
    })
    renderPage()
    await flushPromises()

    fireEvent.change(screen.getByLabelText(/script/i), {
      target: { value: 'A short test script.' },
    })
    fireEvent.change(screen.getByRole('slider', { name: /speech rate/i }), {
      target: { value: '1.3' },
    })
    fireEvent.change(screen.getByRole('slider', { name: /pitch shift/i }), {
      target: { value: '2' },
    })
    fireEvent.change(screen.getByRole('slider', { name: /volume gain/i }), {
      target: { value: '1.1' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Happy' }))
    fireEvent.change(screen.getByLabelText(/delivery direction/i), {
      target: { value: 'Speak cheerfully.' },
    })
    fireEvent.click(screen.getByRole('button', { name: /generate narration/i }))

    await flushPromises()

    const generateCall = fetchSpy.mock.calls.find(
      (c) => String(c[0]).endsWith('/api/builtin-voices/generate'),
    )
    expect(generateCall).toBeTruthy()
    const body = JSON.parse(String((generateCall![1] as RequestInit).body))
    expect(body.delivery_instruction).toBe('Speak cheerfully.')
    expect(body.voice_setting).toMatchObject({
      voice_id: 'Vivian',
      speed: 1.3,
      pitch: 2,
      vol: 1.1,
      emotion: 'happy',
    })
  })
})
