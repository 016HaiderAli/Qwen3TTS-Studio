import { afterEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError } from './api'

afterEach(() => {
  vi.restoreAllMocks()
})

function mockFetch(status: number, body?: unknown) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(
      status === 204 ? null : JSON.stringify(body),
      {
        status,
        headers: { 'Content-Type': 'application/json' },
      },
    ),
  )
}

describe('api client', () => {
  it('returns parsed JSON for success responses', async () => {
    mockFetch(200, { id: 'u1', email: 'a@b.c', name: 'A' })
    const me = await api.me()
    expect(me.email).toBe('a@b.c')
  })

  it('throws ApiError(401) for unauthenticated requests', async () => {
    mockFetch(401, { detail: 'Authentication required.' })
    await expect(api.me()).rejects.toMatchObject({ status: 401 })
    await expect(api.me()).rejects.toThrow(ApiError)
  })

  it('surfaces the API error detail message', async () => {
    mockFetch(409, { detail: 'Voice must be approved before narration.' })
    await expect(
      api.createNarration({
        voice_id: 'v',
        title: '',
        script: 'hi',
        delivery_direction: '',
        language: 'English',
      }),
    ).rejects.toThrow('Voice must be approved before narration.')
  })

  it('returns undefined for 204 responses', async () => {
    mockFetch(204)
    await expect(api.deleteVoice('v1')).resolves.toBeUndefined()
  })

  it('sends same-origin credentials', async () => {
    const spy = mockFetch(200, [])
    await api.listVoices()
    const init = spy.mock.calls[0][1] as RequestInit
    expect(init.credentials).toBe('same-origin')
    expect(init.method ?? 'GET').toBe('GET')
  })
})
