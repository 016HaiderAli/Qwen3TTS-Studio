import { useCallback, useEffect, useRef, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { Wand2, HelpCircle } from 'lucide-react'
import { api, ApiError, type Narration, type Voice } from '../api'
import { AudioPlayer } from '../components/AudioPlayer'
import { ProgressBar } from '../components/ProgressBar'
import { PromptGuideDrawer } from '../components/PromptGuideDrawer'
import { StatusBadge } from '../components/StatusBadge'
import { DEMO_DIALOGUE_SCRIPT, EXPRESSIVE_PRESETS, applyInstructPreset } from '../expressiveness'
import { formatElapsed } from '../format'
import { useInsertSpeakerTag } from '../useInsertSpeakerTag'

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

function VoiceCard({
  voice,
  selected,
  onSelect,
}: {
  voice: Voice
  selected: boolean
  onSelect: () => void
}) {
  return (
    <button
      type="button"
      className={`voice-card ${selected ? 'selected' : ''}`}
      onClick={onSelect}
      aria-pressed={selected}
    >
      <div className="voice-card-head">
        <h3>{`${voice.name} (${voice.language})`}</h3>
        {selected ? null : <StatusBadge status={voice.status} />}
      </div>
      {selected || voice.status !== 'approved' ? null : (
        <p className="muted" style={{ fontSize: '0.78rem' }}>
          {voice.language} · {voice.description || 'No description'}
        </p>
      )}
    </button>
  )
}

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
  const [speed, setSpeed] = useState(1.0)
  const [pitch, setPitch] = useState(0)
  const [isDrawerOpen, setIsDrawerOpen] = useState(false)
  const statusRef = useRef<HTMLDivElement | null>(null)
  const announcedRef = useRef<Set<string>>(new Set())
  const scrolledRef = useRef<Set<string>>(new Set())
  const pollRef = useRef<number | null>(null)
  const scriptRef = useRef<HTMLTextAreaElement>(null)

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

  const { selectRef: nsSelectRef, handleInsertSpeaker: nsHandleInsertTag } = useInsertSpeakerTag(setScript)

  const handleInsertPromptTag = useCallback((tag: string) => {
    setScript((prev) => {
      const separator = prev.length > 0 && !prev.endsWith(' ') && !prev.endsWith('\n') ? ' ' : ''
      return `${prev}${separator}${tag}`
    })
  }, [])

  const handleLoadDemo = useCallback(() => {
    setScript(DEMO_DIALOGUE_SCRIPT)
  }, [])

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
        .catch(() => {})
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
        speed,
        pitch,
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
  const approvedVoices = voices.filter((v) => v.has_approved_prompt)
  const words = script.trim() ? script.trim().split(/\s+/).length : 0
  const charCount = script.length
  const overCharLimit = charCount > MAX_SCRIPT_CHARS
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
        <p className="error-banner" role="alert" style={{ marginBottom: '1rem' }}>
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
          <div className="form-group">
            <label htmlFor="ns-voice-select">Voice</label>
            {loadingVoices ? (
              <p className="muted" style={{ fontSize: '0.85rem' }}>Loading voices…</p>
            ) : approvedVoices.length === 0 ? (
              <>
                <select
                  id="ns-voice-select"
                  className="sr-only"
                  value={voiceId}
                  onChange={(e) => {
                    setVoiceId(e.target.value)
                    const v = voices.find((x) => x.id === e.target.value)
                    if (v && !languageTouchedRef.current) setLanguage(v.language)
                  }}
                  aria-label="Select voice"
                >
                  <option value="" />
                </select>
                <p className="muted" style={{ fontSize: '0.85rem' }}>No approved voices yet.</p>
              </>
            ) : (
              <>
                <select
                  id="ns-voice-select"
                  className="sr-only"
                  value={voiceId}
                  onChange={(e) => {
                    setVoiceId(e.target.value)
                    const v = voices.find((x) => x.id === e.target.value)
                    if (v && !languageTouchedRef.current) setLanguage(v.language)
                  }}
                  aria-label="Select voice"
                >
                  {approvedVoices.map((v) => (
                    <option key={v.id} value={v.id}>{v.name}</option>
                  ))}
                </select>
                <ul className="speaker-grid" role="list" style={{ gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))' }}>
                  {approvedVoices.map((v) => (
                    <li key={v.id}>
                      <VoiceCard
                        voice={v}
                        selected={voiceId === v.id}
                        onSelect={() => {
                          setVoiceId(v.id)
                          if (!languageTouchedRef.current) setLanguage(v.language)
                        }}
                      />
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>

          <div className="form-group">
            <label htmlFor="ns-title">Title</label>
            <input
              id="ns-title"
              className="input"
              value={title}
              onChange={(e) => setTitle(e.target.value)}
              placeholder="Untitled narration"
              disabled={formDisabled}
            />
          </div>

          <div className="form-group">
            <div className="script-header-row">
              <label htmlFor="ns-script">Script</label>
              <div className="script-header-actions">
                <button
                  type="button"
                  className="tool-btn"
                  onClick={() => setIsDrawerOpen(true)}
                >
                  <HelpCircle size={16} />
                  <span>Prompt Helper</span>
                </button>
                <button
                  type="button"
                  className="tool-btn"
                  onClick={handleLoadDemo}
                >
                  Load demo dialogue
                </button>
              </div>
            </div>

            <div className="speaker-tag-strip">
              <span className="dialogue-toolbar-label">
                <Wand2 size={12} strokeWidth={2.5} style={{ display: 'inline', marginRight: 4 }} />
                Speaker tag:
              </span>
              <select
                id="ns-insert-speaker"
                ref={nsSelectRef}
                defaultValue=""
                aria-label="Insert speaker tag"
              >
                <option value="" disabled>Choose voice…</option>
                {approvedVoices.map((v) => (
                  <option key={v.id} value={v.name}>{v.name}</option>
                ))}
              </select>
              <button
                type="button"
                className="btn btn-sm"
                onClick={() => {
                  const ta = scriptRef.current
                  if (ta) nsHandleInsertTag(ta)
                }}
              >
                Insert
              </button>
            </div>

            <textarea
              id="ns-script"
              className="input"
              rows={12}
              ref={scriptRef}
              value={script}
              onChange={(e) => setScript(e.target.value)}
              required
              placeholder="Paste the script to narrate. Separate paragraphs with a blank line — paragraph pauses are preserved."
              disabled={formDisabled}
            />
            <span className="script-meta">
              <span className={overCharLimit ? 'char-limit-warn' : 'muted'}>
                {`${charCount.toLocaleString()} / 100,000 characters`}
              </span>
              <span className="muted"> · {words} words</span>
              {showEstimate && (
                <span className="duration-estimate">
                  {' · '}~{formatElapsed(estimateSec * 1000)} estimated at ~150 words/min
                </span>
              )}
            </span>
          </div>

          <div
            className="expressiveness-group"
            style={{ margin: '1.5rem 0', padding: '1rem', background: 'var(--panel-2)', borderRadius: '8px', border: '1px solid var(--border)' }}
          >
            <h4 style={{ color: 'var(--text)', marginBottom: '1rem' }}>Expressiveness & Audio Controls</h4>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1.5rem' }}>
              <div>
                <label style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                  <span>Speech Rate</span>
                  <span style={{ color: 'var(--primary)', fontWeight: 'bold' }}>{speed.toFixed(1)}x</span>
                </label>
                <input
                  type="range"
                  min={0.5}
                  max={2.0}
                  step={0.1}
                  value={speed}
                  onChange={(e) => setSpeed(parseFloat(e.target.value))}
                  disabled={formDisabled}
                  aria-label={`Speech rate: ${speed.toFixed(1)}x`}
                  style={{ width: '100%', accentColor: 'var(--primary)' }}
                />
              </div>
              <div>
                <label style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)', marginBottom: '0.5rem' }}>
                  <span>Pitch Shift</span>
                  <span style={{ color: 'var(--primary)', fontWeight: 'bold' }}>{pitch > 0 ? `+${pitch}` : pitch} st</span>
                </label>
                <input
                  type="range"
                  min={-12}
                  max={12}
                  step={1}
                  value={pitch}
                  onChange={(e) => setPitch(parseInt(e.target.value, 10))}
                  disabled={formDisabled}
                  aria-label={`Pitch shift: ${pitch} semitones`}
                  style={{ width: '100%', accentColor: 'var(--primary)' }}
                />
              </div>
            </div>
          </div>

          <div className="form-group">
            <label htmlFor="ns-delivery">Delivery / voice direction</label>
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
            <textarea
              id="ns-delivery"
              className="input"
              rows={2}
              value={delivery}
              onChange={(e) => setDelivery(e.target.value)}
              placeholder='Optional: e.g. "Speak slowly and warmly, pause briefly after each sentence."'
              disabled={formDisabled}
            />
          </div>

          <div className="form-group">
            <label htmlFor="ns-language">Language</label>
            <select
              id="ns-language"
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
          </div>

          <button
            className="btn btn-primary btn-block"
            disabled={busy || active || !script.trim() || !voiceId}
          >
            {busy ? 'Starting…' : active ? 'Generating…' : 'Generate narration'}
          </button>
        </form>

        <PromptGuideDrawer
          isOpen={isDrawerOpen}
          onClose={() => setIsDrawerOpen(false)}
          onInsert={handleInsertPromptTag}
        />

        <aside className="studio-status" ref={statusRef}>
          {selectedVoice && (
            <div className="panel">
              <h3>Selected voice</h3>
              {selectedVoice.status === 'approved' ? (
                <>
                  <p className="muted" style={{ fontSize: '0.85rem', marginBottom: '0.5rem' }}>
                    {selectedVoice.name} · {selectedVoice.language}
                    {selectedVoice.description ? ` — ${selectedVoice.description}` : ''}
                  </p>
                  <StatusBadge status={selectedVoice.status} />
                </>
              ) : (
                <>
                  <p className="voice-current-callout" style={{ marginBottom: '0.5rem' }}>
                    This is your current approved voice. It stays usable for narration while a new version is being designed.
                  </p>
                  <StatusBadge status={selectedVoice.status} />
                </>
              )}
              <div style={{ marginTop: '0.75rem' }}>
                <AudioPlayer
                  src={`/api/files/voices/${selectedVoice.id}/reference`}
                  title={`${selectedVoice.name} current approved voice`}
                />
              </div>
            </div>
          )}

          {!loadingVoices && !loadError && approvedVoices.length === 0 && (
            <div className="panel">
              <h3>No approved voices yet</h3>
              <p className="muted" style={{ fontSize: '0.85rem' }}>
                You need at least one approved voice before you can narrate. Design and approve a voice first.
              </p>
              <Link to="/voices" className="btn btn-primary" style={{ marginTop: '0.75rem', display: 'inline-flex' }}>
                Go to voice library
              </Link>
            </div>
          )}

          {active && narration && (
            <div className="panel">
              <h3>Generating</h3>
              {narration.status === 'queued' ? (
                <p className="muted" style={{ fontSize: '0.85rem' }}>
                  Waiting for the GPU worker to pick up your narration…
                  {elapsed ? ` ${elapsed} elapsed` : ''}
                </p>
              ) : (
                <>
                  <p className="muted" style={{ fontSize: '0.85rem', marginBottom: '0.5rem' }}>
                    Chunk {narration.chunks_done} of {narration.chunk_count}
                    {elapsed ? ` · ${elapsed}` : ''}
                  </p>
                  <ProgressBar value={progress} />
                </>
              )}
            </div>
          )}

          {narration?.status === 'ready' && (
            <div className="panel success-panel success-highlight">
              <h3>Ready</h3>
              <p className="muted" style={{ fontSize: '0.85rem', marginBottom: '0.5rem' }}>
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
                style={{ marginTop: '0.75rem', display: 'inline-flex' }}
              >
                Download WAV
              </a>
            </div>
          )}

          {narration?.status === 'failed' && (
            <div className="panel error-panel">
              <h3>Generation failed</h3>
              <p className="muted" style={{ fontSize: '0.85rem' }}>
                {narration.error ?? 'Unknown error.'}
              </p>
              <button
                className="btn btn-primary"
                style={{ marginTop: '0.75rem' }}
                onClick={() => void generate()}
                disabled={busy}
              >
                Retry
              </button>
            </div>
          )}

          {!active && !narration && approvedVoices.length > 0 && (
            <div className="panel">
              <h3>How it works</h3>
              <ol style={{ paddingLeft: '1.2rem', display: 'grid', gap: '0.4rem', color: 'var(--muted)', fontSize: '0.875rem' }}>
                <li>Pick a voice that has an approved version.</li>
                <li>Paste your script.</li>
                <li>Optionally add delivery direction.</li>
                <li>Generate and listen.</li>
              </ol>
              <Link to="/voices" className="btn btn-ghost" style={{ marginTop: '0.75rem', display: 'inline-flex' }}>
                Manage voices
              </Link>
            </div>
          )}
        </aside>
      </div>
    </section>
  )
}
