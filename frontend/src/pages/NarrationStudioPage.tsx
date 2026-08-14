import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, type Narration, type Voice } from '../api'
import { AudioPlayer } from '../components/AudioPlayer'
import { ProgressBar } from '../components/ProgressBar'
import { formatElapsed } from '../format'

const LANGUAGES = [
  'Chinese',
  'English',
  'Japanese',
  'Korean',
  'German',
  'French',
  'Russian',
  'Portuguese',
  'Spanish',
  'Italian',
]

export function NarrationStudioPage() {
  const [params] = useSearchParams()
  const preselect = params.get('voice')

  const [voices, setVoices] = useState<Voice[]>([])
  const [voiceId, setVoiceId] = useState(preselect ?? '')
  const [title, setTitle] = useState('')
  const [script, setScript] = useState('')
  const [delivery, setDelivery] = useState('')
  const [language, setLanguage] = useState('English')
  const [loadingVoices, setLoadingVoices] = useState(true)

  const [narration, setNarration] = useState<Narration | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [announcement, setAnnouncement] = useState('')
  const statusRef = useRef<HTMLDivElement | null>(null)
  const announcedRef = useRef<Set<string>>(new Set())
  const scrolledRef = useRef<Set<string>>(new Set())
  const pollRef = useRef<number | null>(null)

  useEffect(() => {
    void (async () => {
      try {
        const rows = await api.listVoices()
        setVoices(rows)
        if (!preselect && rows.length > 0) setVoiceId(rows[0].id)
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'Failed to load voices.')
      } finally {
        setLoadingVoices(false)
      }
    })()
  }, [preselect])

  const announceOnce = useCallback((id: string, status: string, message: string) => {
    const key = `${id}:${status}`
    if (announcedRef.current.has(key)) return
    announcedRef.current.add(key)
    setAnnouncement(message)
  }, [])

  const scrollOnce = useCallback((id: string) => {
    const key = `scroll:${id}`
    if (scrolledRef.current.has(key)) return
    scrolledRef.current.add(key)
    statusRef.current?.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [])

  // Poll the narration until it reaches a terminal state, announcing and
  // scrolling exactly once when it finishes.
  useEffect(() => {
    const id = narration?.id
    const status = narration?.status
    if (id == null || status == null) return
    if (status === 'ready') {
      announceOnce(id, status, 'Narration ready.')
      scrollOnce(id)
      return
    }
    if (status === 'failed') {
      announceOnce(id, status, 'Narration generation failed.')
      scrollOnce(id)
      return
    }
    if (status !== 'queued' && status !== 'running') return
    pollRef.current = window.setInterval(() => {
      void api
        .getNarration(id)
        .then((n) => setNarration(n))
        .catch(() => {
          // Transient polling failure: keep the last known state and retry on
          // the next tick.
        })
    }, 2000)
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current)
    }
  }, [narration?.id, narration?.status, announceOnce, scrollOnce])

  const generate = async () => {
    if (!script.trim() || !voiceId) return
    setBusy(true)
    setError('')
    try {
      const created = await api.createNarration({
        voice_id: voiceId,
        title,
        script,
        delivery_direction: delivery,
        language,
      })
      setNarration(created)
      setAnnouncement('Generation started.')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not start generation.')
    } finally {
      setBusy(false)
    }
  }

  const active = narration?.status === 'queued' || narration?.status === 'running'
  const formDisabled = busy || active
  const progress =
    narration && narration.chunk_count > 0
      ? Math.round((narration.chunks_done / narration.chunk_count) * 100)
      : 0
  const elapsed = narration
    ? formatElapsed(Date.now() - new Date(narration.created_at).getTime())
    : null

  return (
    <section>
      <div className="page-head">
        <h2>New narration</h2>
      </div>
      <div role="status" aria-live="polite" className="sr-only">
        {announcement}
      </div>
      {error && <p className="error-banner">{error}</p>}

      <div className="studio-layout">
        <form
          className="studio-form"
          onSubmit={(e) => {
            e.preventDefault()
            void generate()
          }}
        >
          <label>
            Voice
            <select
              className="input"
              value={voiceId}
              onChange={(e) => setVoiceId(e.target.value)}
              disabled={loadingVoices || formDisabled}
              required
            >
              {!loadingVoices && voices.length === 0 && <option value="">No voices yet</option>}
              {voices
                .filter((v) => v.status === 'approved')
                .map((v) => (
                  <option key={v.id} value={v.id}>
                    {v.name} ({v.language})
                  </option>
                ))}
            </select>
          </label>
          <label>
            Title
            <input
              className="input"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Untitled narration"
              disabled={formDisabled}
            />
          </label>
          <label>
            Script
            <textarea
              className="input"
              rows={12}
              value={script}
              onChange={(e) => setScript(e.target.value)}
              required
              placeholder="Paste the script to narrate. Separate paragraphs with a blank line — paragraph pauses are preserved."
              disabled={formDisabled}
            />
          </label>
          <label>
            Delivery / voice direction
            <textarea
              className="input"
              rows={2}
              value={delivery}
              onChange={(e) => setDelivery(e.target.value)}
              placeholder="Optional: e.g. “Speak slowly and warmly, pause briefly after each sentence.”"
              disabled={formDisabled}
            />
          </label>
          <label>
            Language
            <select
              className="input"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              disabled={formDisabled}
            >
              {LANGUAGES.map((lang) => (
                <option key={lang}>{lang}</option>
              ))}
            </select>
          </label>
          <button
            className="btn btn-primary btn-block"
            disabled={busy || active || !script.trim() || !voiceId}
          >
            {busy ? 'Starting…' : active ? 'Generating…' : 'Generate narration'}
          </button>
        </form>

        <aside className="studio-status" ref={statusRef}>
          {active && narration && (
            <div className="panel">
              <h3>Generating</h3>
              <p className="muted">
                Chunk {narration.chunks_done} of {narration.chunk_count}
                {elapsed ? ` · ${elapsed} elapsed` : ''}
              </p>
              <ProgressBar value={progress} />
            </div>
          )}
          {narration?.status === 'ready' && (
            <div className="panel success-panel success-highlight">
              <h3>Ready</h3>
              <p className="muted">
                {narration.chunk_count} chunk{narration.chunk_count === 1 ? '' : 's'} ·{' '}
                {narration.duration_sec != null
                  ? `${narration.duration_sec.toFixed(1)} s`
                  : ''}
              </p>
              <AudioPlayer
                src={`/api/files/narrations/${narration.id}/audio`}
                title={narration.title}
              />
              <a
                className="btn btn-primary"
                href={`/api/files/narrations/${narration.id}/audio?download=true`}
              >
                Download WAV
              </a>
            </div>
          )}
          {narration?.status === 'failed' && (
            <div className="panel error-panel">
              <h3>Generation failed</h3>
              <p className="muted">{narration.error ?? 'Unknown error.'}</p>
              <button
                className="btn btn-primary"
                onClick={() => void generate()}
                disabled={busy}
              >
                Retry
              </button>
            </div>
          )}
          {!active && !narration && (
            <div className="panel">
              <h3>How it works</h3>
              <ol className="muted">
                <li>Pick an approved voice.</li>
                <li>Paste your script.</li>
                <li>Optionally add delivery direction.</li>
                <li>Generate and listen.</li>
              </ol>
              <Link to="/voices" className="btn btn-ghost">
                Manage voices
              </Link>
            </div>
          )}
        </aside>
      </div>
    </section>
  )
}
