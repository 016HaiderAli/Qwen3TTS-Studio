// API client. Same-origin requests; in dev the Vite proxy forwards /api and
// /auth to the FastAPI backend so session cookies flow naturally.

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

// Fired when an authenticated request fails with 401/403 outside the initial
// sign-in check, so the app can clear the current user and return to the login
// screen instead of leaving pages stuck on "You are not signed in." banners.
export const SESSION_EXPIRED_EVENT = 'session-expired'

// Suppresses repeated events while the same dead session is being polled. The
// flag is reset on a successful sign-in check (/api/me).
let expiredNotified = false

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const resp = await fetch(path, {
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init,
  })
  if (resp.status === 401 || resp.status === 403) {
    // The initial /api/me check reports "not signed in" as a normal state; a
    // 401/403 on any other request means the session died mid-use.
    if (!path.endsWith('/api/me') && !expiredNotified) {
      expiredNotified = true
      window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT))
    }
    throw new ApiError(resp.status, 'You are not signed in.')
  }
  if (resp.status === 204) {
    return undefined as T
  }
  if (!resp.ok) {
    let detail = resp.statusText
    try {
      const body = await resp.json()
      detail = body?.detail ?? detail
    } catch {
      /* keep default */
    }
    throw new ApiError(resp.status, detail)
  }
  if (path.endsWith('/api/me')) expiredNotified = false
  return resp.json() as Promise<T>
}

export interface Me {
  id: string
  email: string
  name: string
}

export interface Voice {
  id: string
  name: string
  language: string
  description: string
  reference_text: string
  status: 'draft' | 'designing' | 'preview_ready' | 'approving' | 'approved'
  has_approved_prompt: boolean
  created_at: string
  updated_at: string
}

export interface Narration {
  id: string
  voice_id: string
  title: string
  script: string
  delivery_direction: string
  language: string
  status: 'ready' | 'queued' | 'running' | 'failed'
  chunk_count: number
  chunks_done: number
  duration_sec: number | null
  sample_rate: number | null
  error: string | null
  created_at: string
}

export interface NarrationListItem {
  id: string
  title: string
  voice_id: string
  voice_name: string
  status: Narration['status']
  duration_sec: number | null
  created_at: string
}

export interface JobStatus {
  job: {
    id: string
    type: string
    status: string
    progress: number
    error: string | null
  }
  narration: Narration | null
  chunk_total: number
  chunk_done: number
}

export const api = {
  me: () => request<Me>('/api/me'),

  loginUrl: async (): Promise<{ url: string }> => request('/auth/login'),

  listVoices: () => request<Voice[]>('/api/voices'),
  createVoice: (body: {
    name: string
    language: string
    description: string
    reference_text: string
  }) => request<Voice>('/api/voices', { method: 'POST', body: JSON.stringify(body) }),
  designVoice: (
    id: string,
    body: { description: string; reference_text: string; language: string },
  ) => request<Voice>(`/api/voices/${id}/design`, { method: 'POST', body: JSON.stringify(body) }),
  approveVoice: (id: string) =>
    request<Voice>(`/api/voices/${id}/approve`, { method: 'POST' }),
  deleteVoice: (id: string) =>
    request<void>(`/api/voices/${id}`, { method: 'DELETE' }),

  listNarrations: () => request<NarrationListItem[]>('/api/narrations'),
  getNarration: (id: string) => request<Narration>(`/api/narrations/${id}`),
  createNarration: (body: {
    voice_id: string
    title: string
    script: string
    delivery_direction: string
    language: string
  }) => request<Narration>('/api/narrations', { method: 'POST', body: JSON.stringify(body) }),
  deleteNarration: (id: string) =>
    request<void>(`/api/narrations/${id}`, { method: 'DELETE' }),

  job: (id: string) => request<JobStatus>(`/api/jobs/${id}`),
}
