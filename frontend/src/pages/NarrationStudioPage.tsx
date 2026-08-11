import { useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, type Narration, type Voice } from '../api'
import { AudioPlayer } from '../components/AudioPlayer'
import { ProgressBar } from '../components/ProgressBar'

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

  // Poll the narration until it reaches a terminal state.
  useEffect(() => {
    if (!narration || (narration.status !== 'queued' && narration.status !== 'running')) {
      return
    }
    pollRef.current = window.setInterval(() => {
      void api.getNarration(narration.id).then((n) => {
        setNarration(n)
        if (n.status === 'ready' || n.status === 'failed') {
          if (pollRef.current) window.clearInterval(pollRef.current)
        }
      })
    }, 2000)
    return () => {
      if (pollRef.current) window.clearInterval(pollRef.current)
    }
  }, [narration])

  const generate = async (e: React.FormEvent) => {
    e.preventDefault()
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
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not start generation.')
    } finally {
      setBusy(false)
    }
  }

  const active = narration?.status === 'queued' || narration?.status === 'running'
  const progress =
    narration && narration.chunk_count > 0
      ? Math.round((narration.chunks_done / narration.chunk_count) * 100)
      : 0

  return (
    <section>
      <div className="page-head">
        <h2>New narration</h2>
      </div>
      {error && <p className="error-banner">{error}</p>}

      <div className="studio-layout">
        <form className="studio-form" onSubmit={generate}>
          <label>
            Voice
            <select
              className="input"
              value={voiceId}
              onChange={(e) => setVoiceId(e.target.value)}
              disabled={loadingVoices || busy}
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
            />
          </label>
          <label>
            Language
            <select
              className="input"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
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

        <aside className="studio-status">
          {active && narration && (
            <div className="panel">
              <h3>Generating</h3>
              <p className="muted">
                Chunk {narration.chunks_done} of {narration.chunk_count}
              </p>
              <ProgressBar value={progress} />
            </div>
          )}
          {narration?.status === 'ready' && (
            <div className="panel success-panel">
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
