import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api, ApiError, type Voice } from '../api'
import { AudioPlayer } from '../components/AudioPlayer'
import { StatusBadge } from '../components/StatusBadge'

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

export function VoiceLibraryPage() {
  const [voices, setVoices] = useState<Voice[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [designTarget, setDesignTarget] = useState<Voice | null>(null)
  const [createOpen, setCreateOpen] = useState(false)
  const navigate = useNavigate()

  const load = async () => {
    try {
      setVoices(await api.listVoices())
      setError('')
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Failed to load voices.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  // Poll while any voice is being designed or approved.
  const busy = voices.some((v) => v.status === 'designing' || v.status === 'approving')
  useEffect(() => {
    if (!busy) return
    const timer = setInterval(() => void load(), 2000)
    return () => clearInterval(timer)
  }, [busy])

  const approve = async (voice: Voice) => {
    setError('')
    try {
      const updated = await api.approveVoice(voice.id)
      setVoices((prev) => prev.map((v) => (v.id === updated.id ? updated : v)))
    } catch (err) {
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
        <button className="btn btn-primary" onClick={() => setCreateOpen(true)}>
          New voice
        </button>
      </div>
      {error && <p className="error-banner">{error}</p>}
      {loading ? (
        <p className="muted">Loading…</p>
      ) : voices.length === 0 ? (
        <div className="empty-state">
          <p className="muted">
            No voices yet. Create a voice, then generate a design preview.
          </p>
          <button className="btn btn-primary" onClick={() => setCreateOpen(true)}>
            Create your first voice
          </button>
        </div>
      ) : (
        <div className="voice-grid">
          {voices.map((voice) => (
            <VoiceCard
              key={voice.id}
              voice={voice}
              onDesign={() => setDesignTarget(voice)}
              onApprove={() => void approve(voice)}
              onDelete={() => void remove(voice)}
              onUse={() => navigate(`/narration?voice=${voice.id}`)}
            />
          ))}
        </div>
      )}
      {createOpen && (
        <NewVoiceModal
          onClose={() => setCreateOpen(false)}
          onDone={() => {
            setCreateOpen(false)
            void load()
          }}
          onDraft={(voice) => {
            setCreateOpen(false)
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
          onClose={() => setDesignTarget(null)}
          onSubmitted={(updated) => {
            setVoices((prev) => prev.map((v) => (v.id === updated.id ? updated : v)))
            setDesignTarget(null)
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
      <div className="modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <h3>Create & design voice</h3>
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
  onDesign,
  onApprove,
  onDelete,
  onUse,
}: {
  voice: Voice
  onDesign: () => void
  onApprove: () => void
  onDelete: () => void
  onUse: () => void
}) {
  const referenceSrc = `/api/files/voices/${voice.id}/reference`
  const downloadable = voice.status === 'preview_ready' || voice.status === 'approved'
  return (
    <article className="voice-card">
      <div className="voice-card-head">
        <h3>{voice.name}</h3>
        <StatusBadge status={voice.status} />
      </div>
      <p className="muted">
        {voice.language}
        {voice.description ? ` — ${voice.description}` : ''}
      </p>
      {voice.status === 'designing' && (
        <p className="muted">Creating your voice preview… (takes a minute on the GPU)</p>
      )}
      {voice.status === 'approving' && (
        <p className="muted">Saving this voice for narrations… (takes a few moments on the GPU)</p>
      )}
      {voice.status === 'preview_ready' && (
        <p className="muted voice-approval-hint">
          Happy with this preview? Approve it to save this voice for narration. This builds a
          reusable voice signature from the clip — it takes a few moments on the GPU.
        </p>
      )}
      {downloadable && (
        <AudioPlayer src={referenceSrc} title={`${voice.name} reference`} />
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
            <button className="btn btn-primary" onClick={onApprove}>
              Approve
            </button>
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
      <div className="modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <h3>Design voice — {voice.name}</h3>
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
