import { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, ApiError, type Narration } from '../api'
import { AudioPlayer } from '../components/AudioPlayer'
import { StatusBadge } from '../components/StatusBadge'
import { EXPRESSIVE_PRESETS, applyInstructPreset } from '../expressiveness'
import { SPEAKERS, getSpeaker } from '../customVoices'
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

export function BuiltinVoicesPage() {
  const [speakers] = useState(SPEAKERS)
  const [selectedSpeaker, setSelectedSpeaker] = useState(SPEAKERS[0].id)
  const [language, setLanguage] = useState('English')
  const [script, setScript] = useState('')
  const [instruct, setInstruct] = useState('')
  const [title, setTitle] = useState('')
  const [generating, setGenerating] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState<Narration | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const [generatingId, setGeneratingId] = useState<string | null>(null)
  const announcedRef = useRef(false)
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const speaker = getSpeaker(selectedSpeaker) ?? SPEAKERS[0]

  useEffect(() => {
    if (result === null || result.status === 'queued' || result.status === 'running') {
      if (pollTimerRef.current !== null) return
      pollTimerRef.current = setInterval(async () => {
        if (generatingId === null) return
        try {
          const updated = await api.getNarration(generatingId)
          setResult(updated)
          if (updated.status === 'ready' || updated.status === 'failed') {
            if (pollTimerRef.current !== null) {
              clearInterval(pollTimerRef.current)
              pollTimerRef.current = null
            }
          }
        } catch {
          // keep polling
        }
      }, 2000)
    } else {
      if (pollTimerRef.current !== null) {
        clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
      }
    }
    return () => {
      if (pollTimerRef.current !== null) {
        clearInterval(pollTimerRef.current)
        pollTimerRef.current = null
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result?.status, generatingId])

  useEffect(() => {
    if (result === null) return
    if (result.status !== 'ready' && result.status !== 'failed') return
    if (announcedRef.current) return
    announcedRef.current = true
    if (result.status === 'ready') {
      setAnnouncement(`Narration "${result.title}" is ready.`)
    } else {
      setAnnouncement(`Narration "${result.title}" failed.`)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result?.status, result?.title])

  const generate = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!script.trim()) {
      setError('Please enter a script.')
      return
    }
    setError('')
    setGenerating(true)
    setResult(null)
    announcedRef.current = false
    setAnnouncement('')
    try {
      const narration = await api.generateBuiltinVoice({
        speaker: selectedSpeaker,
        language,
        script: script.trim(),
        instruct: instruct.trim(),
        title: title.trim(),
      })
      setGeneratingId(narration.id)
      setResult(narration)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Generation failed.')
      setGenerating(false)
    }
  }

  const reset = () => {
    setResult(null)
    setGenerating(false)
    setGeneratingId(null)
    setAnnouncement('')
    announcedRef.current = false
  }

  const handlePreset = (presetIdx: number) => {
    const preset = EXPRESSIVE_PRESETS[presetIdx]
    setInstruct((prev) => applyInstructPreset(prev, preset, prev.trim().length > 0))
  }

  const elapsed =
    result !== null && (result.status === 'queued' || result.status === 'running')
      ? formatElapsed(Date.now() - new Date(result.created_at).getTime())
      : null

  const showForm = result === null || result.status === 'failed'

  return (
    <section>
      <div className="page-head">
        <h2>Built-in Voices</h2>
      </div>
      <div role="status" aria-live="polite" className="sr-only">
        {announcement}
      </div>

      <div className="builtin-layout">
        <div className="builtin-sidebar">
          <h3>Speakers</h3>
          <ul className="speaker-grid" role="list">
            {speakers.map((s) => (
              <li key={s.id}>
                <button
                  type="button"
                  className={`speaker-card ${selectedSpeaker === s.id ? 'selected' : ''}`}
                  onClick={() => setSelectedSpeaker(s.id)}
                  aria-pressed={selectedSpeaker === s.id}
                >
                  <span className="speaker-name">{s.displayName}</span>
                  <span className="speaker-lang muted">{s.nativeLanguage}</span>
                </button>
              </li>
            ))}
          </ul>
        </div>

        <div className="builtin-main">
          <div className="speaker-profile">
            <h3>{speaker.displayName}</h3>
            <p className="muted">{speaker.nativeLanguage} · Built-in Qwen voice</p>
            <p className="speaker-desc">{speaker.description}</p>
          </div>

          {showForm ? (
            <form onSubmit={generate} className="builtin-form">
              <div className="form-group">
                <label htmlFor="bv-language">Language</label>
                <select
                  id="bv-language"
                  value={language}
                  onChange={(e) => setLanguage(e.target.value)}
                >
                  {LANGUAGES.map((l) => (
                    <option key={l} value={l}>{l}</option>
                  ))}
                </select>
              </div>

              <div className="form-group">
                <label htmlFor="bv-title">Title (optional)</label>
                <input
                  id="bv-title"
                  type="text"
                  value={title}
                  onChange={(e) => setTitle(e.target.value)}
                  placeholder="e.g. My first narration"
                  maxLength={300}
                />
              </div>

              <div className="form-group">
                <label htmlFor="bv-script">Script *</label>
                <textarea
                  id="bv-script"
                  value={script}
                  onChange={(e) => setScript(e.target.value)}
                  placeholder="Enter the text you want to narrate…"
                  rows={10}
                  required
                />
                <span className="field-hint">{script.length} / 100,000 chars</span>
              </div>

              <div className="form-group">
                <label htmlFor="bv-instruct">
                  Delivery direction{' '}
                  <span className="field-hint inline">optional — describe how it should sound</span>
                </label>
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
                <input
                  id="bv-instruct"
                  type="text"
                  value={instruct}
                  onChange={(e) => setInstruct(e.target.value)}
                  placeholder="e.g. warm and friendly, slightly slower pace"
                  maxLength={2000}
                />
              </div>

              {error && (
                <div className="error-banner" role="alert">
                  {error}
                </div>
              )}

              <button type="submit" className="btn btn-primary" disabled={generating}>
                {generating ? 'Generating…' : 'Generate narration'}
              </button>
            </form>
          ) : (
            <div className="builtin-result">
              <div className="builtin-result-header">
                <div>
                  <h3>{result.title}</h3>
                  <p className="muted">
                    {speaker.displayName} · {result.language}
                    {elapsed ? ` · ${elapsed} elapsed` : ''}
                  </p>
                </div>
                <StatusBadge status={result.status} />
              </div>

              {result.status === 'ready' && (
                <AudioPlayer
                  src={`/api/files/narrations/${result.id}/audio`}
                  title={result.title}
                />
              )}

              {result.status === 'failed' && result.error && (
                <div className="error-banner" role="alert">
                  {result.error}
                </div>
              )}

              <div className="builtin-result-actions">
                <button type="button" className="btn" onClick={reset}>
                  New narration
                </button>
                <Link to="/history" className="btn btn-ghost">
                  View history
                </Link>
              </div>
            </div>
          )}
        </div>
      </div>
    </section>
  )
}
