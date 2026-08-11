import { useEffect, useState } from 'react'
import { api, ApiError, type NarrationListItem } from '../api'
import { AudioPlayer } from '../components/AudioPlayer'
import { StatusBadge } from '../components/StatusBadge'

export function HistoryPage() {
  const [items, setItems] = useState<NarrationListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = async () => {
    try {
      setItems(await api.listNarrations())
      setError('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load history.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  const remove = async (id: string, title: string) => {
    if (!window.confirm(`Delete narration "${title}"?`)) return
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
      {error && <p className="error-banner">{error}</p>}
      {loading ? (
        <p className="muted">Loading…</p>
      ) : items.length === 0 ? (
        <div className="empty-state">
          <p className="muted">No narrations yet. Create one from the studio.</p>
        </div>
      ) : (
        <ul className="history-list">
          {items.map((item) => (
            <li key={item.id} className="history-row">
              <div className="history-main">
                <h3>{item.title}</h3>
                <p className="muted">
                  {item.voice_name} · {item.created_at.slice(0, 16).replace('T', ' ')} ·{' '}
                  {item.duration_sec != null ? `${item.duration_sec.toFixed(1)} s` : '—'}
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
              <button
                className="btn btn-ghost"
                onClick={() => void remove(item.id, item.title)}
              >
                Delete
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
