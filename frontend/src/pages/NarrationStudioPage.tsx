import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, ApiError, type Narration, type Voice } from '../api'
import { AudioPlayer } from '../components/AudioPlayer'
import { ProgressBar } from '../components/ProgressBar'
import { StatusBadge } from '../components/StatusBadge'
import { EXPRESSIVE_PRESETS, applyInstructPreset } from '../expressiveness'
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

const MAX_SCRIPT_CHARS = 100_000
const ESTIMATED_WORDS_PER_MINUTE = 150

export function NarrationStudioPage() {
  const [params] = useSearchParams()
  const preselect = params.get('voice')
  const reuseId = params.get('reuse')

  const [voices, setVoices] = useState<Voice[]>([])
  const [voiceId, setVoiceId] = useState('')
  const [title, setTitle] = useState('')
  const [script, setScript] = useState('')
  const [delivery, setDelivery] = useState('')
  const [language, setLanguage] = useState('English')
  const [loadingVoices, setLoadingVoices] = useState(true)
  const [loadError, setLoadError] = useState('')
  const languageTouchedRef = useRef(false)

  const [narration, setNarration] = useState<Narration | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [announcement, setAnnouncement] = useState('')
  const statusRef = useRef<HTMLDivElement | null>(null)
  const announcedRef = useRef<Set<string>>(new Set())
  const scrolledRef = useRef<Set<string>>(new Set())
  const pollRef = useRef<number | null>(null)

  // Loads the approved voices and (optionally) the narration to reuse, then
  // preselects a voice. Re-runs whenever the ?voice= / ?reuse= params change
  // and can be triggered again from the load-error Retry action.
  const load = useCallback(async () => {
    const selectVoice = (rows: Voice[], preferred?: string | null) => {
      const approved = rows.filter((v) => v.has_approved_prompt)
      if (preferred) {
        const match = approved.find((v) => v.id === preferred)
        if (match) return match
      }
      return approved[0] ?? null
    }
    setLoadingVoices(true)
    setLoadError('')
    try {
      const rows = await api.listVoices()
      setVoices(rows)
      const syncLanguage = (voice: Voice) => {
        if (!languageTouchedRef.current) setLanguage(voice.language)
      }
      if (reuseId) {
        try {
          const reuse = await api.getNarration(reuseId)
          setTitle(reuse.title)
          setScript(reuse.script)
          setDelivery(reuse.delivery_direction)
          setLanguage(reuse.language)
          languageTouchedRef.current = true
          const voice = selectVoice(rows, preselect ?? reuse.voice_id)
          if (voice) setVoiceId(voice.id)
        } catch (err) {
          setLoadError(
            err instanceof ApiError && err.status === 404
              ? 'Narration not found.'
              : err instanceof ApiError
                ? err.message
                : 'Could not load the narration to reuse.',
          )
          const voice = selectVoice(rows, preselect)
          if (voice) {
            setVoiceId(voice.id)
            syncLanguage(voice)
          }
        }
      } else {
        const voice = selectVoice(rows, preselect)
        if (voice) {
          setVoiceId(voice.id)
          syncLanguage(voice)
        }
      }
    } catch (err) {
      setLoadError(err instanceof ApiError ? err.message : 'Failed to load voices.')
    } finally {
      setLoadingVoices(false)
    }
  }, [preselect, reuseId])

  useEffect(() => {
    void load()
  }, [load])

  const retryLoad = async () => {
    await load()
  }

  const handlePreset = (presetIdx: number) => {
    const preset = EXPRESSIVE_PRESETS[presetIdx]
    setDelivery((prev) => applyInstructPreset(prev, preset, prev.trim().length > 0))
  }

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

  const selectedVoice = voices.find((v) => v.id === voiceId && v.has_approved_prompt) ?? null
  const approvedCount = voices.filter((v) => v.has_approved_prompt).length
  const words = script.trim() ? script.trim().split(/\s+/).length : 0
  const charCount = script.length
  const overCharLimit = charCount > MAX_SCRIPT_CHARS
  // Rough heuristic (~150 wpm). Clearly labeled as an estimate in the UI and
  // replaced by the measured duration once generation completes.
  const estimateSec = words > 0 ? Math.round((words / ESTIMATED_WORDS_PER_MINUTE) * 60) : 0
  const showEstimate = !narration && !active && words > 0

  return (
    <section>
      <div className="page-head">
        <h2>New narration</h2>
      </div>
      <div role="status" aria-live="polite" className="sr-only">
        {announcement}
      </div>
      {loadError && (
        <div className="error-banner error-banner-row" role="alert">
          <span>{loadError}</span>
          <button className="btn" onClick={() => void retryLoad()}>
            Retry
          </button>
        </div>
      )}
      {error && (
        <p className="error-banner" role="alert">
          {error}
        </p>
      )}

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
              onChange={(e) => {
                const id = e.target.value
                setVoiceId(id)
                const picked = voices.find((v) => v.id === id && v.has_approved_prompt)
                if (picked && !languageTouchedRef.current) setLanguage(picked.language)
              }}
              disabled={loadingVoices || formDisabled}
              required
            >
              {!loadingVoices && !loadError && approvedCount === 0 && (
                <option value="">No approved voices yet</option>
              )}
              {voices
                .filter((v) => v.has_approved_prompt)
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
          <span className="muted script-meta">
            <span className={overCharLimit ? 'char-limit-warn' : undefined}>
              {charCount.toLocaleString()} / {MAX_SCRIPT_CHARS.toLocaleString()} characters
            </span>
            <span>· {words} words</span>
            {showEstimate && (
              <span className="duration-estimate">
                · ~{formatElapsed(estimateSec * 1000)} estimated at ~150 words/min
              </span>
            )}
          </span>
          <div className="preset-chips" role="group" aria-label="Expressive presets">
            {EXPRESSIVE_PRESETS.map((p, i) => (
              <button
                key={p.label}
                type="button"
                className="preset-chip"
                onClick={() => handlePreset(i)}
              >
                {p.label}
              </button>
            ))}
          </div>
          <label>
            Delivery / voice direction
            <textarea
              className="input"
              rows={2}
              value={delivery}
              onChange={(e) => setDelivery(e.target.value)}
              placeholder='Optional: e.g. "Speak slowly and warmly, pause briefly after each sentence."'
              disabled={formDisabled}
            />
          </label>
          <label>
            Language
            <select
              className="input"
              value={language}
              onChange={(e) => {
                setLanguage(e.target.value)
                languageTouchedRef.current = true
              }}
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
          {selectedVoice && (
            <div className="panel">
              <h3>Selected voice</h3>
              {selectedVoice.status === 'approved' ? (
                <>
                  <p className="muted">
                    {selectedVoice.name} · {selectedVoice.language}
                    {selectedVoice.description ? ` — ${selectedVoice.description}` : ''}
                  </p>
                  <StatusBadge status={selectedVoice.status} />
                </>
              ) : (
                <>
                  <p className="muted voice-current-callout">
                    This is your current approved voice. It stays usable for narration while a new
                    version is being designed; the redesign is a replacement candidate.
                  </p>
                  <StatusBadge status={selectedVoice.status} />
                </>
              )}
              <AudioPlayer
                src={`/api/files/voices/${selectedVoice.id}/reference`}
                title={`${selectedVoice.name} current approved voice`}
              />
            </div>
          )}
          {!loadingVoices && !loadError && approvedCount === 0 && (
            <div className="panel">
              <h3>No approved voices yet</h3>
              <p className="muted">
                You need at least one approved voice before you can narrate. Design and approve a
                voice first.
              </p>
              <Link to="/voices" className="btn btn-primary">
                Go to voice library
              </Link>
            </div>
          )}
          {active && narration && (
            <div className="panel">
              <h3>Generating</h3>
              {narration.status === 'queued' ? (
                <p className="muted">
                  Waiting for the GPU worker to pick up your narration…
                  {elapsed ? ` ${elapsed} elapsed` : ''}
                </p>
              ) : (
                <>
                  <p className="muted">
                    Chunk {narration.chunks_done} of {narration.chunk_count}
                    {elapsed ? ` · ${elapsed} elapsed` : ''}
                  </p>
                  <ProgressBar value={progress} />
                </>
              )}
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
          {!active && !narration && approvedCount > 0 && (
            <div className="panel">
              <h3>How it works</h3>
              <ol className="muted">
                <li>Pick a voice that has an approved version.</li>
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
