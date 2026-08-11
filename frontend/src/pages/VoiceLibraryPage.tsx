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

export function VoiceLibraryPage() {
  const [voices, setVoices] = useState<Voice[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [designTarget, setDesignTarget] = useState<Voice | null>(null)
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

  // Poll while any voice is being designed.
  const designing = voices.some((v) => v.status === 'designing')
  useEffect(() => {
    if (!designing) return
    const timer = setInterval(() => void load(), 2000)
    return () => clearInterval(timer)
  }, [designing])

  const approve = async (voice: Voice) => {
    setError('')
    try {
      const updated = await api.approveVoice(voice.id)
      setVoices((prev) => prev.map((v) => (v.id === updated.id ? updated : v)))
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Approval failed.')
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
        <CreateVoiceForm onCreated={() => void load()} />
      </div>
      {error && <p className="error-banner">{error}</p>}
      {loading ? (
        <p className="muted">Loading…</p>
      ) : voices.length === 0 ? (
        <div className="empty-state">
          <p className="muted">
            No voices yet. Create a voice, then generate a design preview.
          </p>
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

function CreateVoiceForm({ onCreated }: { onCreated: () => void }) {
  const [name, setName] = useState('')
  const [language, setLanguage] = useState('English')
  const [description, setDescription] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!name.trim()) return
    setBusy(true)
    setError('')
    try {
      await api.createVoice({ name, language, description })
      setName('')
      setDescription('')
      onCreated()
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not create voice.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="create-voice" onSubmit={submit}>
      <input
        className="input"
        placeholder="Voice name"
        value={name}
        onChange={(e) => setName(e.target.value)}
        required
      />
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
      <input
        className="input grow"
        placeholder="Short description (optional)"
        value={description}
        onChange={(e) => setDescription(e.target.value)}
      />
      <button className="btn btn-primary" disabled={busy || !name.trim()}>
        {busy ? 'Creating…' : 'Create voice'}
      </button>
      {error && <p className="error-banner">{error}</p>}
    </form>
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
        <p className="muted">The GPU worker is designing a preview voice…</p>
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

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const updated = await api.designVoice(voice.id, {
        description,
        reference_text: referenceText,
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
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" onClick={(e) => e.stopPropagation()}>
        <h3>Design voice — {voice.name}</h3>
        <form onSubmit={submit}>
          <label>
            Voice description
            <textarea
              className="input"
              rows={3}
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              required
              placeholder="e.g. Warm and friendly, with a calm measured pace and a gentle smile."
            />
          </label>
          <label>
            Reference text (a sentence the designed voice will speak)
            <textarea
              className="input"
              rows={2}
              value={referenceText}
              onChange={(e) => setReferenceText(e.target.value)}
              required
              placeholder="e.g. Welcome to our story. Enjoy the journey."
            />
          </label>
          <label>
            Language
            <select className="input" value={language} onChange={(e) => setLanguage(e.target.value)}>
              {LANGUAGES.map((lang) => (
                <option key={lang}>{lang}</option>
              ))}
            </select>
          </label>
          {error && <p className="error-banner">{error}</p>}
          <div className="modal-actions">
            <button type="button" className="btn btn-ghost" onClick={onClose} disabled={busy}>
              Cancel
            </button>
            <button className="btn btn-primary" disabled={busy}>
              {busy ? 'Designing…' : 'Generate preview'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
