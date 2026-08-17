import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError, type Voice } from '../api'
import { AudioPlayer } from '../components/AudioPlayer'
import { Spinner } from '../components/Spinner'
import { StatusBadge } from '../components/StatusBadge'
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

const MAX_FIELD_LENGTH = 2000

const DESCRIPTION_EXAMPLES = [
  'Warm and friendly, with a calm measured pace and a gentle smile.',
  'Deep, calm male narrator with a cold, analytical tone and steady pacing.',
  'Crisp, energetic news anchor with clear pronunciation.',
  'Soft and soothing, like a bedtime story reader.',
]

const REFERENCE_EXAMPLES = [
  'Welcome to our story. Enjoy the journey.',
  "Good evening, everyone. Let's see what happens next.",
  'It was a quiet morning, and the city was just beginning to wake up.',
]

const DESCRIPTION_HINT =
  'Describe the voice you want in plain language — personality, tone, age/gender feel, pacing, emotion. Qwen uses this exact description to build the voice.'

const REFERENCE_HINT =
  'This exact sentence will be spoken by your new voice so you can judge it. Use 1–2 natural sentences that show off the voice.'

function statusAnnouncement(voice: Voice, prev: string | undefined): string | null {
  const { name, status, has_approved_prompt } = voice
  if (prev === 'designing' && status === 'draft') {
    return `Design failed for ${name}.`
  }
  if (prev === 'designing' && status === 'approved') {
    return `Redesign failed for ${name}. Your approved voice is still available.`
  }
  if (prev === 'approving' && status === 'preview_ready') {
    return has_approved_prompt
      ? `Approval failed for ${name}. Your approved voice is still available.`
      : `Approval failed for ${name}. The preview is still available.`
  }
  if (prev === 'designing' && status === 'preview_ready' && has_approved_prompt) {
    return `A new preview for ${name} is ready. Approve it to replace your current approved version.`
  }
  switch (status) {
    case 'designing':
      return has_approved_prompt
        ? `Generating a new version of ${name}…`
        : `Designing ${name}…`
    case 'preview_ready':
      return `${name} preview is ready.`
    case 'approving':
      return `Approving ${name}…`
    case 'approved':
      return `${name} is approved and ready for narration.`
    default:
      return null
  }
}

export function VoiceLibraryPage() {
  const [voices, setVoices] = useState<Voice[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [designTarget, setDesignTarget] = useState<Voice | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const [approvingId, setApprovingId] = useState<string | null>(null)
  const [announcement, setAnnouncement] = useState('')
  const [highlightId, setHighlightId] = useState<string | null>(null)
  const announcedRef = useRef<Set<string>>(new Set())
  const prevStatusRef = useRef<Record<string, string>>({})
  const seededRef = useRef(false)
  const navigate = useNavigate()
  const lastTriggerRef = useRef<HTMLElement | null>(null)

  const load = async () => {
    try {
      setVoices(await api.listVoices())
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load voices.')
    } finally {
      setLoading(false)
    }
  }

  const retryLoad = async () => {
    setError('')
    setLoading(true)
    await load()
  }

  const openCreate = () => {
    lastTriggerRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    setCreateOpen(true)
  }

  const closeCreate = () => {
    setCreateOpen(false)
    lastTriggerRef.current?.focus()
    lastTriggerRef.current = null
  }

  const openDesign = (voice: Voice) => {
    lastTriggerRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null
    setDesignTarget(voice)
  }

  const closeDesign = () => {
    setDesignTarget(null)
    lastTriggerRef.current?.focus()
    lastTriggerRef.current = null
  }

  useEffect(() => {
    void load()
  }, [])

  // Announce status transitions exactly once per voice+transition.
  useEffect(() => {
    if (voices.length === 0) return
    const next = { ...prevStatusRef.current }
    const messages: string[] = []
    for (const voice of voices) {
      const prev = prevStatusRef.current[voice.id]
      const status = voice.status
      next[voice.id] = status
      if (!seededRef.current || prev === status) continue
      // Key on the transition so a redesign cycle (approved -> designing ->
      // approved) can announce again instead of being suppressed by the
      // earlier 'approved' announcement.
      const key = `${voice.id}:${prev}->${status}`
      if (announcedRef.current.has(key)) continue
      announcedRef.current.add(key)
      const msg = statusAnnouncement(voice, prev)
      if (msg) messages.push(msg)
      const failedRedesign = prev === 'designing' && status === 'approved'
      if ((status === 'preview_ready' || status === 'approved') && !failedRedesign) {
        setHighlightId(voice.id)
      }
    }
    prevStatusRef.current = next
    if (!seededRef.current) {
      seededRef.current = true
      return
    }
    if (messages.length > 0) setAnnouncement(messages.join(' '))
  }, [voices])

  // Poll while any voice is being designed or approved.
  const busy = voices.some((v) => v.status === 'designing' || v.status === 'approving')
  useEffect(() => {
    if (!busy) return
    const timer = setInterval(() => void load(), 2000)
    return () => clearInterval(timer)
  }, [busy])

  const approve = async (voice: Voice) => {
    setError('')
    setApprovingId(voice.id)
    try {
      const updated = await api.approveVoice(voice.id)
      setApprovingId(null)
      setVoices((prev) => prev.map((v) => (v.id === updated.id ? updated : v)))
    } catch (err) {
      setApprovingId(null)
      setError(err instanceof ApiError ? err.message : 'Approval failed.')
      void load()
    }
  }

  const remove = async (voice: Voice) => {
    if (!window.confirm(`Delete voice "${voice.name}"? This cannot be undone.`)) return
    setError('')
    try {
      await api.deleteVoice(voice.id)
      setVoices((prev) => prev.filter((v) => v.id !== voice.id))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Delete failed.')
    }
  }

  return (
    <section>
      <div className="page-head">
        <h2>Voice Library</h2>
        <button className="btn btn-primary" onClick={openCreate}>
          New voice
        </button>
      </div>
      <div role="status" aria-live="polite" className="sr-only">
        {announcement}
      </div>
      {error && (
        <div className="error-banner error-banner-row">
          <span>{error}</span>
          <button className="btn" onClick={() => void retryLoad()}>
            Retry
          </button>
        </div>
      )}
      {loading ? (
        <p className="muted">Loading…</p>
      ) : voices.length === 0 ? (
        error ? null : (
          <div className="empty-state">
            <p className="muted">
              No voices yet. Create a voice, then generate a design preview.
            </p>
            <button className="btn btn-primary" onClick={openCreate}>
              Create your first voice
            </button>
          </div>
        )
      ) : (
        <div className="voice-grid">
          {voices.map((voice) => (
            <VoiceCard
              key={voice.id}
              voice={voice}
              highlighted={voice.id === highlightId}
              approvePending={approvingId === voice.id}
              onDesign={() => openDesign(voice)}
              onApprove={() => void approve(voice)}
              onDelete={() => void remove(voice)}
              onUse={() => navigate(`/narration?voice=${voice.id}`)}
            />
          ))}
        </div>
      )}
      {createOpen && (
        <NewVoiceModal
          onClose={closeCreate}
          onDone={() => {
            closeCreate()
            void load()
          }}
          onDraft={(voice) => {
            closeCreate()
            setVoices((prev) =>
              prev.some((v) => v.id === voice.id) ? prev : [voice, ...prev],
            )
          }}
          onError={(msg) => setError(msg)}
        />
      )}
      {designTarget && (
        <DesignVoiceModal
          voice={designTarget}
          onClose={closeDesign}
          onSubmitted={(updated) => {
            setVoices((prev) => prev.map((v) => (v.id === updated.id ? updated : v)))
            closeDesign()
          }}
          onError={(msg) => setError(msg)}
        />
      )}
    </section>
  )
}

function NewVoiceModal({
  onClose,
  onDone,
  onDraft,
  onError,
}: {
  onClose: () => void
  onDone: () => void
  onDraft: (voice: Voice) => void
  onError: (msg: string) => void
}) {
  const [name, setName] = useState('')
  const [language, setLanguage] = useState('English')
  const [description, setDescription] = useState('')
  const [referenceText, setReferenceText] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy) onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [busy, onClose])

  const canSubmit = name.trim() && description.trim() && referenceText.trim() && !busy

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit) return
    setBusy(true)
    setError('')
    try {
      const created = await api.createVoice({
        name: name.trim(),
        language,
        description: description.trim(),
        reference_text: referenceText.trim(),
      })
      try {
        await api.designVoice(created.id, {
          description: description.trim(),
          reference_text: referenceText.trim(),
          language,
        })
        onDone()
      } catch (err) {
        const msg = err instanceof ApiError ? err.message : 'Design failed. Please try again.'
        // The voice record exists as a draft; show it and let the user retry.
        onDraft(created)
        onError(msg)
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create voice.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={busy ? undefined : onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="new-voice-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id="new-voice-modal-title">Create &amp; design voice</h3>
        <form onSubmit={submit}>
          <div className="field">
            <span className="field-title">Voice name</span>
            <input
              className="input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              aria-label="Voice name"
              placeholder="e.g. Documentary narrator"
            />
          </div>
          <div className="field">
            <span className="field-title">Language</span>
            <select
              className="input"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              aria-label="Language"
            >
              {LANGUAGES.map((lang) => (
                <option key={lang}>{lang}</option>
              ))}
            </select>
          </div>
          <VoiceSpecFields
            prefix="new-voice"
            description={description}
            referenceText={referenceText}
            onDescriptionChange={setDescription}
            onReferenceTextChange={setReferenceText}
          />
          {error && <p className="error-banner">{error}</p>}
          <div className="modal-actions">
            <button type="button" className="btn btn-ghost" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button className="btn btn-primary" disabled={!canSubmit}>
              {busy ? 'Creating…' : 'Create voice & generate preview'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

function VoiceSpecFields({
  prefix,
  description,
  referenceText,
  onDescriptionChange,
  onReferenceTextChange,
}: {
  prefix: string
  description: string
  referenceText: string
  onDescriptionChange: (value: string) => void
  onReferenceTextChange: (value: string) => void
}) {
  return (
    <>
      <div className="field">
        <span className="field-title">Voice description</span>
        <textarea
          className="input"
          rows={3}
          value={description}
          onChange={(e) => onDescriptionChange(e.target.value)}
          required
          maxLength={MAX_FIELD_LENGTH}
          aria-label="Voice description"
          aria-describedby={`${prefix}-description-hint`}
          placeholder="e.g. A calm, deep narrator with a steady, measured pace."
        />
        <p id={`${prefix}-description-hint`} className="field-hint">
          {DESCRIPTION_HINT}
        </p>
        <ExampleChips
          label="Voice description examples"
          options={DESCRIPTION_EXAMPLES}
          onPick={onDescriptionChange}
          current={description}
        />
        <CharCount value={description} max={MAX_FIELD_LENGTH} />
      </div>
      <div className="field">
        <span className="field-title">Reference text</span>
        <textarea
          className="input"
          rows={2}
          value={referenceText}
          onChange={(e) => onReferenceTextChange(e.target.value)}
          required
          maxLength={MAX_FIELD_LENGTH}
          aria-label="Reference text"
          aria-describedby={`${prefix}-reference-hint`}
          placeholder="e.g. Welcome to our story. Enjoy the journey."
        />
        <p id={`${prefix}-reference-hint`} className="field-hint">
          {REFERENCE_HINT}
        </p>
        <ExampleChips
          label="Reference text examples"
          options={REFERENCE_EXAMPLES}
          onPick={onReferenceTextChange}
          current={referenceText}
        />
        <CharCount value={referenceText} max={MAX_FIELD_LENGTH} />
      </div>
    </>
  )
}

function ExampleChips({
  label,
  options,
  onPick,
  current,
}: {
  label: string
  options: string[]
  onPick: (value: string) => void
  current: string
}) {
  return (
    <div className="chips" role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option}
          type="button"
          className={`chip${option === current ? ' chip-active' : ''}`}
          onClick={() => onPick(option)}
        >
          {option}
        </button>
      ))}
    </div>
  )
}

function CharCount({ value, max }: { value: string; max: number }) {
  return (
    <span className="char-count">
      {value.length} / {max}
    </span>
  )
}

function VoiceCard({
  voice,
  highlighted,
  approvePending,
  onDesign,
  onApprove,
  onDelete,
  onUse,
}: {
  voice: Voice
  highlighted: boolean
  approvePending: boolean
  onDesign: () => void
  onApprove: () => void
  onDelete: () => void
  onUse: () => void
}) {
  const hasApprovedPrompt = voice.has_approved_prompt
  const isRedesign = hasApprovedPrompt && voice.status !== 'approved'
  const referenceSrc = `/api/files/voices/${voice.id}/reference`
  const busyStatus = voice.status === 'designing' || voice.status === 'approving'
  const downloadable =
    voice.status === 'preview_ready' ||
    voice.status === 'approved' ||
    (hasApprovedPrompt && busyStatus)
  const elapsed = busyStatus
    ? formatElapsed(Date.now() - new Date(voice.updated_at).getTime())
    : null
  return (
    <article className={`voice-card${highlighted ? ' success-highlight' : ''}`}>
      <div className="voice-card-head">
        <h3>{voice.name}</h3>
        <StatusBadge status={voice.status} />
      </div>
      <p className="muted">
        {voice.language}
        {voice.description ? ` — ${voice.description}` : ''}
      </p>
      {voice.status === 'designing' && (
        <p className="muted voice-busy-line">
          <Spinner label="Designing voice" />
          <span>
            {hasApprovedPrompt
              ? 'Creating a new version of your approved voice…'
              : 'Creating your voice preview…'}
          </span>
          {elapsed && <span className="elapsed"> · {elapsed} elapsed</span>}
        </p>
      )}
      {voice.status === 'approving' && (
        <p className="muted voice-busy-line">
          <Spinner label="Approving voice" />
          <span>
            {hasApprovedPrompt
              ? 'Saving this new version to replace your approved voice…'
              : 'Saving this voice for narrations…'}
          </span>
          {elapsed && <span className="elapsed"> · {elapsed} elapsed</span>}
        </p>
      )}
      {hasApprovedPrompt && voice.status === 'approved' && (
        <p className="muted voice-current-callout">This is your current approved version.</p>
      )}
      {isRedesign && (
        <p className="muted voice-current-callout">
          Your current approved version stays available for narration until you approve the new
          one.
        </p>
      )}
      {voice.status === 'preview_ready' && (
        <p className="muted voice-approval-hint">
          {hasApprovedPrompt
            ? 'Happy with this new version? Approving it replaces your current approved voice for narration.'
            : 'Happy with this preview? Approve it to save this voice for narration. This builds a reusable voice signature from the clip — it takes a few moments on the GPU.'}
        </p>
      )}
      {downloadable && (
        <AudioPlayer
          src={referenceSrc}
          title={
            hasApprovedPrompt && voice.status === 'preview_ready'
              ? `${voice.name} new version preview`
              : hasApprovedPrompt && busyStatus
                ? `${voice.name} current approved version`
                : `${voice.name} reference`
          }
        />
      )}
      <div className="voice-actions">
        {voice.status === 'draft' && (
          <button className="btn btn-primary" onClick={onDesign}>
            Design voice
          </button>
        )}
        {voice.status === 'approving' && (
          <button className="btn btn-primary" disabled title="Approval in progress">
            Approving…
          </button>
        )}
        {voice.status === 'preview_ready' && (
          <>
            {approvePending ? (
              <button className="btn btn-primary" disabled title="Approval in progress">
                Approving…
              </button>
            ) : (
              <button className="btn btn-primary" onClick={onApprove}>
                Approve
              </button>
            )}
            <button className="btn" onClick={onDesign}>
              Redesign
            </button>
          </>
        )}
        {voice.status === 'approved' && (
          <>
            <button className="btn btn-primary" onClick={onUse}>
              Use for narration
            </button>
            <button className="btn" onClick={onDesign}>
              Redesign
            </button>
          </>
        )}
        {hasApprovedPrompt && voice.status !== 'approved' && (
          <button className="btn" onClick={onUse} title="Uses your current approved version">
            Use for narration
          </button>
        )}
        <button className="btn btn-ghost" onClick={onDelete}>
          Delete
        </button>
      </div>
    </article>
  )
}

function DesignVoiceModal({
  voice,
  onClose,
  onSubmitted,
  onError,
}: {
  voice: Voice
  onClose: () => void
  onSubmitted: (voice: Voice) => void
  onError: (msg: string) => void
}) {
  const [description, setDescription] = useState(voice.description)
  const [referenceText, setReferenceText] = useState(voice.reference_text)
  const [language, setLanguage] = useState(voice.language)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !busy) onClose()
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [busy, onClose])

  const canSubmit = description.trim() && referenceText.trim() && !busy

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!canSubmit) return
    setBusy(true)
    setError('')
    try {
      const updated = await api.designVoice(voice.id, {
        description: description.trim(),
        reference_text: referenceText.trim(),
        language,
      })
      onSubmitted(updated)
    } catch (err) {
      const msg = err instanceof ApiError ? err.message : 'Design failed.'
      setError(msg)
      onError(msg)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="modal-backdrop" onClick={busy ? undefined : onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="design-voice-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 id="design-voice-modal-title">
          {voice.has_approved_prompt ? 'Redesign voice' : 'Design voice'} — {voice.name}
        </h3>
        {voice.has_approved_prompt && (
          <p className="muted voice-current-callout">
            Your current approved version stays available for narration until you approve the new
            one.
          </p>
        )}
        <form onSubmit={submit}>
          <VoiceSpecFields
            prefix="redesign"
            description={description}
            referenceText={referenceText}
            onDescriptionChange={setDescription}
            onReferenceTextChange={setReferenceText}
          />
          <div className="field">
            <span className="field-title">Language</span>
            <select
              className="input"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              aria-label="Language"
            >
              {LANGUAGES.map((lang) => (
                <option key={lang}>{lang}</option>
              ))}
            </select>
          </div>
          {error && <p className="error-banner">{error}</p>}
          <div className="modal-actions">
            <button type="button" className="btn btn-ghost" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button className="btn btn-primary" disabled={!canSubmit}>
              {busy ? 'Designing…' : 'Generate preview'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
