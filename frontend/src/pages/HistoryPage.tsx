import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError, type NarrationListItem } from '../api'
import { AudioPlayer } from '../components/AudioPlayer'
import { StatusBadge } from '../components/StatusBadge'
import { formatElapsed } from '../format'

export function HistoryPage() {
  const [items, setItems] = useState<NarrationListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [announcement, setAnnouncement] = useState('')
  const [errorDetailId, setErrorDetailId] = useState<string | null>(null)
  const [errorDetailBody, setErrorDetailBody] = useState<Record<string, string>>({})
  const [errorDetailFailure, setErrorDetailFailure] = useState<Record<string, string>>({})
  const errorDetailLoadingRef = useRef<Set<string>>(new Set())
  const announcedRef = useRef<Set<string>>(new Set())
  const seededRef = useRef(false)

  const load = async () => {
    try {
      setItems(await api.listNarrations())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load history.')
    } finally {
      setLoading(false)
    }
  }

  const retryLoad = async () => {
    setError('')
    setLoading(true)
    await load()
  }

  const toggleErrorDetails = async (id: string) => {
    if (errorDetailId === id) {
      setErrorDetailId(null)
      return
    }
    setErrorDetailId(id)
    if (errorDetailBody[id] !== undefined || errorDetailFailure[id] !== undefined) return
    if (errorDetailLoadingRef.current.has(id)) return
    errorDetailLoadingRef.current.add(id)
    try {
      const narration = await api.getNarration(id)
      setErrorDetailBody((prev) => ({
        ...prev,
        [id]: narration.error ?? 'No error message provided.',
      }))
    } catch (err) {
      setErrorDetailFailure((prev) => ({
        ...prev,
        [id]: err instanceof ApiError ? err.message : 'Could not load error details.',
      }))
    } finally {
      errorDetailLoadingRef.current.delete(id)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  // Announce terminal transitions exactly once per narration+status. Items
  // already in a terminal state on first load are treated as known so the
  // initial render is not announced as a transition.
  useEffect(() => {
    if (items.length === 0) return
    for (const item of items) {
      if (item.status !== 'ready' && item.status !== 'failed') continue
      const key = `${item.id}:${item.status}`
      if (!seededRef.current) {
        announcedRef.current.add(key)
        continue
      }
      if (announcedRef.current.has(key)) continue
      announcedRef.current.add(key)
      if (item.status === 'ready') {
        setAnnouncement(`Narration "${item.title}" is ready.`)
      } else {
        setAnnouncement(`Narration "${item.title}" failed.`)
      }
    }
    seededRef.current = true
  }, [items])

  // Poll while any narration is being generated.
  const active = items.some((n) => n.status === 'queued' || n.status === 'running')
  useEffect(() => {
    if (!active) return
    const timer = setInterval(() => void load(), 2000)
    return () => clearInterval(timer)
  }, [active])

  const remove = async (id: string, title: string) => {
    if (!window.confirm(`Delete narration "${title}"?`)) return
    setError('')
    try {
      await api.deleteNarration(id)
      setItems((prev) => prev.filter((n) => n.id !== id))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Delete failed.')
    }
  }

  return (
    <section>
      <div className="page-head">
        <h2>History</h2>
      </div>
      <div role="status" aria-live="polite" className="sr-only">
        {announcement}
      </div>
      {error && (
        <div className="error-banner error-banner-row" role="alert">
          <span>{error}</span>
          <button className="btn" onClick={() => void retryLoad()}>
            Retry
          </button>
        </div>
      )}
      {loading ? (
        <p className="muted">Loading…</p>
      ) : items.length === 0 ? (
        error ? null : (
          <div className="empty-state">
            <p className="muted">No narrations yet. Create one from the studio.</p>
            <Link to="/narration" className="btn btn-primary">
              Create a narration
            </Link>
          </div>
        )
      ) : (
        <ul className="history-list">
          {items.map((item) => {
            const activeItem = item.status === 'queued' || item.status === 'running'
            const elapsed = activeItem
              ? formatElapsed(Date.now() - new Date(item.created_at).getTime())
              : null
            return (
              <li key={item.id} className="history-row">
                <div className="history-main">
                  <h3>{item.title}</h3>
                  <p className="muted">
                    {item.voice_name} · {item.created_at.slice(0, 16).replace('T', ' ')} ·{' '}
                    {item.duration_sec != null ? `${item.duration_sec.toFixed(1)} s` : '—'}
                    {elapsed ? ` · ${elapsed} elapsed` : ''}
                  </p>
                  <StatusBadge status={item.status} />
                </div>
                {item.status === 'ready' && (
                  <div className="history-actions">
                    <AudioPlayer
                      src={`/api/files/narrations/${item.id}/audio`}
                      title={item.title}
                    />
                    <a
                      className="btn"
                      href={`/api/files/narrations/${item.id}/audio?download=true`}
                    >
                      Download
                    </a>
                  </div>
                )}
                {(item.status === 'ready' || item.status === 'failed') && (
                  <Link
                    className="btn"
                    to={`/narration?reuse=${item.id}&voice=${item.voice_id}`}
                  >
                    Reuse in studio
                  </Link>
                )}
                {item.status === 'failed' && (
                  <button
                    className="btn"
                    aria-expanded={errorDetailId === item.id}
                    aria-controls={`narration-error-${item.id}`}
                    onClick={() => void toggleErrorDetails(item.id)}
                  >
                    Error details
                  </button>
                )}
                <button
                  className="btn btn-ghost"
                  onClick={() => void remove(item.id, item.title)}
                >
                  Delete
                </button>
                {item.status === 'failed' && errorDetailId === item.id && (
                  <div
                    id={`narration-error-${item.id}`}
                    className="history-error-detail"
                  >
                    {errorDetailFailure[item.id] !== undefined ? (
                      <p className="error-banner">{errorDetailFailure[item.id]}</p>
                    ) : errorDetailBody[item.id] !== undefined ? (
                      <p className="muted">{errorDetailBody[item.id]}</p>
                    ) : (
                      <p className="muted">Loading error details…</p>
                    )}
                  </div>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
