import { useCallback, useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { Wand2, PlusCircle, Play, Pause, HelpCircle } from 'lucide-react'
import { api, ApiError, type Narration, type Voice } from '../api'
import { AudioPlayer } from '../components/AudioPlayer'
import { PromptGuideDrawer } from '../components/PromptGuideDrawer'
import { StatusBadge } from '../components/StatusBadge'
import { DEMO_DIALOGUE_SCRIPT, EXPRESSIVE_PRESETS, applyInstructPreset } from '../expressiveness'
import { SPEAKERS, getSpeaker, type SpeakerInfo } from '../customVoices'
import { formatElapsed } from '../format'
import { useInsertSpeakerTag } from '../useInsertSpeakerTag'

import vivianSample from '/samples/Vivian.wav?url'
import serenaSample from '/samples/Serena.wav?url'
import uncleFuSample from '/samples/Uncle_Fu.wav?url'
import dylanSample from '/samples/Dylan.wav?url'
import ericSample from '/samples/Eric.wav?url'
import ryanSample from '/samples/Ryan.wav?url'
import aidenSample from '/samples/Aiden.wav?url'
import onoAnnaSample from '/samples/Ono_Anna.wav?url'
import soheeSample from '/samples/Sohee.wav?url'

const SAMPLE_MAP: Record<string, string> = {
  Vivian: vivianSample,
  Serena: serenaSample,
  Uncle_Fu: uncleFuSample,
  Dylan: dylanSample,
  Eric: ericSample,
  Ryan: ryanSample,
  Aiden: aidenSample,
  Ono_Anna: onoAnnaSample,
  Sohee: soheeSample,
}

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

function SpeakerCard({
  speaker,
  selected,
  onSelect,
  isPlaying,
  previewError,
  onPlayToggle,
}: {
  speaker: SpeakerInfo
  selected: boolean
  onSelect: () => void
  isPlaying: boolean
  previewError: string | null
  onPlayToggle: () => void
}) {
  const genderClass =
    speaker.gender === 'MALE' ? 'male' : speaker.gender === 'FEMALE' ? 'female' : 'neutral'

  return (
    <div
      role="button"
      tabIndex={0}
      className={`speaker-card ${selected ? 'selected' : ''} ${isPlaying ? 'playing' : ''}`}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onSelect()
        }
      }}
      aria-pressed={selected}
      aria-label={`${speaker.displayName}, ${speaker.gender.toLowerCase()}, ${speaker.nativeLanguage}`}
    >
      <div className="speaker-card-header">
        <div className="speaker-avatar">
          <button
            type="button"
            className="preview-btn"
            onClick={(e) => {
              e.stopPropagation()
              onPlayToggle()
            }}
            aria-label={isPlaying ? `Pause ${speaker.displayName} preview` : `Play ${speaker.displayName} preview`}
          >
            {isPlaying ? <Pause size={16} /> : <Play size={16} />}
          </button>
        </div>
        <div className="speaker-info">
          <span className="speaker-name">{speaker.displayName}</span>
          <span className="speaker-lang">{speaker.nativeLanguage}</span>
        </div>
      </div>
      <div className="speaker-badges">
        <span className={`lang-badge ${genderClass}`}>{speaker.gender}</span>
        <span className="lang-badge neutral">{speaker.nativeLanguage.split(' ')[0]}</span>
      </div>
      <p className="speaker-desc">{speaker.description}</p>
      {previewError && (
        <p className="preview-error" role="alert">{previewError}</p>
      )}
    </div>
  )
}

export function BuiltinVoicesPage() {
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
  const [playingSpeakerId, setPlayingSpeakerId] = useState<string | null>(null)
  const [previewErrors, setPreviewErrors] = useState<Record<string, string>>({})
  const [customVoices, setCustomVoices] = useState<Voice[]>([])
  const [speed, setSpeed] = useState(1.0)
  const [pitch, setPitch] = useState(0)
  const [isDrawerOpen, setIsDrawerOpen] = useState(false)
  const announcedRef = useRef(false)
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const scriptRef = useRef<HTMLTextAreaElement>(null)
  const audioRef = useRef<HTMLAudioElement | null>(null)

  const speaker = getSpeaker(selectedSpeaker) ?? SPEAKERS[0]

  const approvedCustomVoices = customVoices.filter((v) => v.status === 'approved')
  const allSpeakerOptions = [
    ...SPEAKERS.map((s) => ({ id: s.id, name: s.displayName, language: s.nativeLanguage, gender: s.gender, description: s.description, isCustom: false })),
    ...approvedCustomVoices.map((v) => ({ id: v.name, name: v.name, language: v.language || 'English', gender: 'NEUTRAL' as const, description: v.description || '', isCustom: true })),
  ]

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
    void api.listVoices().then(setCustomVoices).catch(() => {})
  }, [])

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
        speed,
        pitch,
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

  const stopPreview = () => {
    if (audioRef.current) {
      audioRef.current.pause()
      audioRef.current = null
    }
    setPlayingSpeakerId(null)
  }

  const handlePlayToggle = async (speakerId: string) => {
    if (playingSpeakerId === speakerId) {
      stopPreview()
      return
    }
    stopPreview()
    const speaker = getSpeaker(speakerId)
    if (!speaker) return

    setPreviewErrors((prev) => {
      const next = { ...prev }
      delete next[speakerId]
      return next
    })

    const sampleUrl = SAMPLE_MAP[speakerId]
    if (!sampleUrl) {
      setPreviewErrors((prev) => ({ ...prev, [speakerId]: 'Sample unavailable' }))
      return
    }

    try {
      const audio = new Audio(sampleUrl)
      audioRef.current = audio
      audio.play().catch(() => {})
      setPlayingSpeakerId(speakerId)
      audio.onended = () => {
        setPlayingSpeakerId(null)
        audioRef.current = null
      }
    } catch (err) {
      console.error(`[Preview Error] ${speakerId}:`, err)
      setPreviewErrors((prev) => ({ ...prev, [speakerId]: 'Sample unavailable' }))
    }
  }

  const handlePreset = (presetIdx: number) => {
    const preset = EXPRESSIVE_PRESETS[presetIdx]
    setInstruct((prev) => applyInstructPreset(prev, preset, prev.trim().length > 0))
  }

  const handleInsertPromptTag = useCallback((tag: string) => {
    setScript((prev) => {
      const separator = prev.length > 0 && !prev.endsWith(' ') && !prev.endsWith('\n') ? ' ' : ''
      return `${prev}${separator}${tag}`
    })
  }, [])

  const handleLoadDemo = useCallback(() => {
    setScript(DEMO_DIALOGUE_SCRIPT)
  }, [])

  const { selectRef: bvSelectRef, handleInsertSpeaker: bvHandleInsertTag } = useInsertSpeakerTag(setScript)

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

      <div className="studio-layout" style={{ gridTemplateColumns: '1fr' }}>
        <div>
          <ul className="speaker-grid" role="list">
            {SPEAKERS.map((s) => (
              <li key={s.id}>
                <SpeakerCard
                  speaker={s}
                  selected={selectedSpeaker === s.id}
                  onSelect={() => {
                    setSelectedSpeaker(s.id)
                    if (playingSpeakerId) stopPreview()
                  }}
                  isPlaying={playingSpeakerId === s.id}
                  previewError={previewErrors[s.id] ?? null}
                  onPlayToggle={() => handlePlayToggle(s.id)}
                />
              </li>
            ))}
          </ul>
        </div>

        <div className="studio-form" style={{ marginTop: '1.5rem' }}>
          <div className="speaker-card-header" style={{ marginBottom: '1rem' }}>
            <div className="speaker-avatar" style={{ width: 52, height: 52 }}>
              <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M12 2a3 3 0 0 0-3 3v7a3 3 0 0 0 6 0V5a3 3 0 0 0-3-3Z"/>
                <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
                <line x1="12" x2="12" y1="19" y2="22"/>
              </svg>
            </div>
            <div className="speaker-info">
              <span className="speaker-name" style={{ fontSize: '1.1rem' }}>{speaker.displayName}</span>
              <span className="speaker-lang">{speaker.nativeLanguage} · Built-in Qwen voice</span>
            </div>
          </div>
          <p className="muted" style={{ fontSize: '0.875rem', marginBottom: '1.25rem' }}>{speaker.description}</p>

          {showForm ? (
            <form onSubmit={generate}>
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
                <label htmlFor="bv-title">Title <span className="field-hint">(optional)</span></label>
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

                <div className="dialogue-toolbar">
                  <span className="dialogue-toolbar-label">
                    <Wand2 size={12} strokeWidth={2.5} style={{ display: 'inline', marginRight: 4 }} />
                    Speaker tag
                  </span>
                  <select
                    id="bv-insert-speaker"
                    ref={bvSelectRef}
                    defaultValue=""
                    aria-label="Insert speaker tag"
                  >
                    <option value="" disabled>Choose…</option>
                    {allSpeakerOptions.map((s) => (
                      <option key={s.id} value={s.id}>{s.name}</option>
                    ))}
                  </select>
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => {
                      const ta = scriptRef.current
                      if (ta) bvHandleInsertTag(ta)
                    }}
                  >
                    Insert
                  </button>
                  <div style={{ display: 'flex', gap: '0.5rem', marginLeft: 'auto' }}>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={() => setIsDrawerOpen(true)}
                      style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem', padding: '0.4rem 0.8rem', cursor: 'pointer' }}
                    >
                      <HelpCircle size={16} />
                      <span>Prompt Helper</span>
                    </button>
                    <button
                      type="button"
                      className="btn-secondary"
                      onClick={handleLoadDemo}
                      style={{ display: 'inline-flex', alignItems: 'center', gap: '0.4rem', padding: '0.4rem 0.8rem', cursor: 'pointer' }}
                    >
                      Load demo dialogue
                    </button>
                  </div>
                </div>

                <textarea
                  id="bv-script"
                  ref={scriptRef}
                  value={script}
                  onChange={(e) => setScript(e.target.value)}
                  placeholder="Enter the text you want to narrate…"
                  rows={10}
                  required
                />
                <span className="field-hint" style={{ marginTop: '0.25rem' }}>
                  {script.length.toLocaleString()} / 100,000 chars
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
                      disabled={generating}
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
                      disabled={generating}
                      aria-label={`Pitch shift: ${pitch} semitones`}
                      style={{ width: '100%', accentColor: 'var(--primary)' }}
                    />
                  </div>
                </div>
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
                <div className="error-banner" role="alert" style={{ marginBottom: '1rem' }}>
                  {error}
                </div>
              )}

              <button type="submit" className="btn btn-primary btn-block" disabled={generating}>
                {generating ? 'Generating…' : 'Generate narration'}
              </button>
            </form>
          ) : (
            <div>
              <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '0.75rem', marginBottom: '1rem', flexWrap: 'wrap' }}>
                <div>
                  <h3 style={{ fontSize: '1rem', marginBottom: '0.2rem' }}>{result.title}</h3>
                  <p className="muted" style={{ fontSize: '0.8rem' }}>
                    {speaker.displayName} · {result.language}
                    {elapsed ? ` · ${elapsed}` : ''}
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
                <div className="error-banner" role="alert" style={{ marginBottom: '1rem' }}>
                  {result.error}
                </div>
              )}

              <div style={{ display: 'flex', gap: '0.5rem', marginTop: '1rem', flexWrap: 'wrap' }}>
                <button type="button" className="btn" onClick={reset}>
                  <PlusCircle size={14} strokeWidth={2} />
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

      <PromptGuideDrawer
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        onInsert={handleInsertPromptTag}
      />
    </section>
  )
}
