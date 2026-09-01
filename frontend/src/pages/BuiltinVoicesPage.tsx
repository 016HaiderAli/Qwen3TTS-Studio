import { useCallback, useEffect, useRef, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Wand2, PlusCircle, HelpCircle, FileAudio } from 'lucide-react'
import { api, ApiError, type Narration, type Voice } from '../api'
import { AudioPlayer } from '../components/AudioPlayer'
import { DialogueSegmentDisplay } from '../components/DialogueSegmentDisplay'
import { ExportFormatSelector } from '../components/ExportFormatSelector'
import { PromptGuideDrawer } from '../components/PromptGuideDrawer'
import { StatusBadge } from '../components/StatusBadge'
import { VoicePreviewBar } from '../components/VoicePreviewBar'
import { VoiceSelector, type VoiceOption } from '../components/VoiceSelector'
import { DEMO_DIALOGUE_SCRIPT, EXPRESSIVE_PRESETS, applyInstructPreset } from '../expressiveness'
import { SPEAKERS, getSpeaker } from '../customVoices'
import { formatElapsed } from '../format'
import { useInsertSpeakerTag } from '../useInsertSpeakerTag'

// Phase 6B polish: every built-in speaker's preview is served by the public
// /api/voices/{id}/preview backend endpoint (Content-Disposition: inline,
// Accept-Ranges: bytes). URLs are strictly lower-case and RELATIVE, so the
// requests travel through the Vite dev proxy to the FastAPI backend and stay
// same-origin — no CORS preflight at all. The frontend fetches the bytes and
// decodes them through Web Audio so no direct media URL or DOM audio element
// is ever presented to a browser download manager.
const BUILTIN_SAMPLE_URLS: Record<string, string> = Object.fromEntries(
  SPEAKERS.map((s) => [s.id, `/api/voices/${s.id.toLowerCase()}/preview`]),
)

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

const SINGLE_DEMO_SCRIPT =
  'Welcome to Voice Studio. This sample script is narrated by the single speaker you selected — no speaker tags required.'

type GenerationMode = 'single' | 'multi'

export function BuiltinVoicesPage() {
  const [params] = useSearchParams()
  const requestedVoice = params.get('voice')

  const [generationMode, setGenerationMode] = useState<GenerationMode>('single')
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
  const [customVoices, setCustomVoices] = useState<Voice[]>([])
  const [speed, setSpeed] = useState(1.0)
  const [pitch, setPitch] = useState(0)
  const [isDrawerOpen, setIsDrawerOpen] = useState(false)
  const announcedRef = useRef(false)
  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const scriptRef = useRef<HTMLTextAreaElement>(null)

  // Phase 6A: unified voice options across built-in speakers and approved
  // custom voices. Option ids are the API identifiers (speaker id or custom
  // voice UUID); names are display-only.
  const voiceOptions: VoiceOption[] = [
    ...SPEAKERS.map((s) => ({
      kind: 'builtin' as const,
      id: s.id,
      name: s.displayName,
      language: s.nativeLanguage,
      description: s.description,
    })),
    ...customVoices
      .filter((v) => v.status === 'approved')
      .map((v) => ({
        kind: 'custom' as const,
        id: v.id,
        name: v.name,
        language: v.language || 'English',
        description: v.description || '',
      })),
  ]

  // ?voice=<id> deep link: preselect a built-in speaker or approved custom voice.
  useEffect(() => {
    if (!requestedVoice) return
    const match = voiceOptions.find(
      (o) => o.id === requestedVoice || o.name === requestedVoice,
    )
    if (match) setSelectedSpeaker(match.id)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestedVoice, customVoices.length])

  const isBuiltin = getSpeaker(selectedSpeaker) !== undefined
  const builtinSpeaker = getSpeaker(selectedSpeaker)
  const activeCustom = isBuiltin ? null : customVoices.find((v) => v.id === selectedSpeaker && v.status === 'approved')
  const activeName = isBuiltin ? (builtinSpeaker?.displayName ?? selectedSpeaker) : (activeCustom?.name ?? selectedSpeaker)
  const activePill = isBuiltin
    ? `${builtinSpeaker?.nativeLanguage ?? ''} · Built-in`
    : `Custom · ${activeCustom?.language ?? ''}`
  const activeSample = isBuiltin
    ? BUILTIN_SAMPLE_URLS[selectedSpeaker] ?? null
    : activeCustom
      ? // Approved custom voices stream their live reference audio through the
        // authenticated endpoint — fetched as an ArrayBuffer in the preview bar.
        `/api/files/voices/${activeCustom.id}/reference`
      : null

  // Multi-speaker dialogue mode tag strip options: every voice can appear as
  // a [Speaker: …] tag in the script, so the strip values are display names.
  const allSpeakerOptions = voiceOptions.map((o) => ({
    id: o.name,
    name: o.name,
    language: o.language,
    isCustom: o.kind === 'custom',
  }))

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
      // Phase 6A unified flow: built-in speakers use the CustomVoice endpoint;
      // approved custom voices narrate through the cloned-voice narration API.
      const narration = isBuiltin
        ? await api.generateBuiltinVoice({
            speaker: selectedSpeaker,
            language,
            script: script.trim(),
            instruct: instruct.trim(),
            title: title.trim(),
            speed,
            pitch,
          })
        : await api.createNarration({
            voice_id: activeCustom?.id ?? '',
            title: title.trim(),
            script: script.trim(),
            delivery_direction: instruct.trim(),
            language,
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
    setScript(generationMode === 'single' ? SINGLE_DEMO_SCRIPT : DEMO_DIALOGUE_SCRIPT)
  }, [generationMode])

  const { selectRef: bvSelectRef, handleInsertSpeaker: bvHandleInsertTag } = useInsertSpeakerTag(setScript)

  const elapsed =
    result !== null && (result.status === 'queued' || result.status === 'running')
      ? formatElapsed(Date.now() - new Date(result.created_at).getTime())
      : null

  const processing =
    result !== null && (result.status === 'queued' || result.status === 'running')
  const finished =
    result !== null && (result.status === 'ready' || result.status === 'failed')
  const progressPct =
    result !== null && result.chunk_count > 0
      ? Math.min(100, Math.round((result.chunks_done / result.chunk_count) * 100))
      : 6

  return (
    <section>
      <div className="page-head">
        <h2>Built-in Voices</h2>
      </div>
      <div role="status" aria-live="polite" className="sr-only">
        {announcement}
      </div>

      <div className="mode-toggle" role="group" aria-label="Generation mode">
        <button
          type="button"
          className={`mode-toggle-option ${generationMode === 'single' ? 'active' : ''}`}
          onClick={() => setGenerationMode('single')}
          aria-pressed={generationMode === 'single'}
        >
          Single Voice
        </button>
        <button
          type="button"
          className={`mode-toggle-option ${generationMode === 'multi' ? 'active' : ''}`}
          onClick={() => setGenerationMode('multi')}
          aria-pressed={generationMode === 'multi'}
        >
          Multi-Speaker Dialogue
        </button>
      </div>

      <div className="studio-layout">
        <div className="studio-form">
          <div className="form-group">
            <label>Voice</label>
            <VoiceSelector
              options={voiceOptions}
              value={selectedSpeaker}
              onChange={setSelectedSpeaker}
            />
          </div>

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

              <VoicePreviewBar name={activeName} pill={activePill} sampleSrc={activeSample} />

              <div className="form-group">
                <div className="script-header-row">
                  <label htmlFor="bv-script">Script *</label>
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
                      {generationMode === 'single' ? 'Load sample text' : 'Load demo dialogue'}
                    </button>
                  </div>
                </div>

                {generationMode === 'multi' && (
                  <div className="speaker-tag-strip">
                    <span className="dialogue-toolbar-label">
                      <Wand2 size={12} strokeWidth={2.5} style={{ display: 'inline', marginRight: 4 }} />
                      Speaker tag:
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
                  </div>
                )}

                <textarea
                  id="bv-script"
                  ref={scriptRef}
                  value={script}
                  onChange={(e) => setScript(e.target.value)}
                  placeholder={
                    generationMode === 'single'
                      ? 'Enter the script to narrate...'
                      : 'Enter dialogue with speaker tags, e.g.,\n[Speaker: Vivian] Hello!\n[Speaker: Senku] High-tech science time!'
                  }
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
        </div>

        <aside className="output-panel" aria-label="Generation output">
          {result === null && (
            <div className="output-idle">
              <div className="output-idle-icon">
                <FileAudio size={24} strokeWidth={1.8} />
              </div>
              <p className="output-idle-title">Your generated narration audio will appear here</p>
              <p className="muted">
                Pick a voice, write a script, and press “Generate narration”.
              </p>
            </div>
          )}

          {result !== null && processing && (
            <div className="output-processing">
              <div className="output-panel-header">
                <div>
                  <h3>Generating narration</h3>
                  <p className="muted">{result.title} · {activeName}</p>
                </div>
                <StatusBadge status={result.status} />
              </div>
              <div
                className="output-progress-track"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={progressPct}
                aria-label="Generation progress"
              >
                <div className="output-progress-bar" style={{ width: `${progressPct}%` }} />
              </div>
              <p className="muted output-progress-label">
                {result.status === 'queued'
                  ? 'Queued — waiting for the GPU worker…'
                  : result.chunk_count > 1
                    ? `Generating chunk ${Math.min(result.chunks_done + 1, result.chunk_count)} of ${result.chunk_count}`
                    : 'Generating audio…'}
                {elapsed ? ` · ${elapsed} elapsed` : ''}
              </p>
            </div>
          )}

          {result !== null && finished && (
            <div className="output-result">
              <div className="output-panel-header">
                <div>
                  <h3>{result.title}</h3>
                  <p className="muted">
                    {activeName} · {result.language}
                    {result.status === 'ready' && result.duration_sec != null
                      ? ` · ${result.duration_sec.toFixed(1)} s`
                      : ''}
                  </p>
                </div>
                <div className="output-panel-badges">
                  {result.dialogue_speaker_count > 1 && (
                    <span className="multi-speaker-badge">
                      {result.dialogue_speaker_count}-Speaker
                    </span>
                  )}
                  <StatusBadge status={result.status} />
                </div>
              </div>

              {result.status === 'ready' && (
                <>
                  <AudioPlayer
                    src={`/api/files/narrations/${result.id}/audio`}
                    title={result.title}
                  />
                  <div className="output-actions">
                    <ExportFormatSelector narrationId={result.id} />
                    <button type="button" className="btn" onClick={reset}>
                      <PlusCircle size={14} strokeWidth={2} />
                      New narration
                    </button>
                  </div>
                  <div className="output-script-block">
                    <h4>Script</h4>
                    {result.dialogue_speaker_count > 1 ? (
                      <DialogueSegmentDisplay segments={result.dialogue_segments} />
                    ) : (
                      <p className="script-readout">{result.script}</p>
                    )}
                  </div>
                </>
              )}

              {result.status === 'failed' && (
                <>
                  {result.error && (
                    <div className="error-banner" role="alert">
                      {result.error}
                    </div>
                  )}
                  <button
                    type="button"
                    className="btn"
                    onClick={reset}
                    style={{ marginTop: '1rem' }}
                  >
                    <PlusCircle size={14} strokeWidth={2} />
                    Try again
                  </button>
                </>
              )}
            </div>
          )}
        </aside>
      </div>

      <PromptGuideDrawer
        isOpen={isDrawerOpen}
        onClose={() => setIsDrawerOpen(false)}
        onInsert={handleInsertPromptTag}
      />
    </section>
  )
}
