import { useCallback, useEffect, useRef, useState } from 'react'
import { Upload, X, Mic } from 'lucide-react'
import { api, ApiError } from '../api'
import { VoicePreviewBar } from './VoicePreviewBar'

const MAX_UPLOAD_BYTES = 20 * 1024 * 1024 // 20 MiB, matches backend limit
const ACCEPTED_EXTENSIONS = ['.wav', '.mp3', '.m4a', '.ogg']

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

/**
 * Phase 7A voice-clone modal: drag-and-drop a 3-10 s reference clip, name the
 * voice, pick a language, preview the clip through the shared waveform player,
 * then clone. On success the parent receives the registered voice so it can
 * offer a direct "Use in TTS Studio" jump.
 */
export function VoiceCloneModal({
  onClose,
  onCloned,
}: {
  onClose: () => void
  onCloned: (result: { id: string; display_name: string }) => void
}) {
  const [file, setFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [displayName, setDisplayName] = useState('')
  const [language, setLanguage] = useState('English')
  const [error, setError] = useState('')
  const [cloning, setCloning] = useState(false)
  const [dragActive, setDragActive] = useState(false)
  const inputRef = useRef<HTMLInputElement | null>(null)

  // Revoke the previous object URL whenever the clip changes or modal unmounts.
  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl)
    }
  }, [previewUrl])

  const acceptFile = useCallback((candidate: File | undefined | null) => {
    if (!candidate) return
    const lower = candidate.name.toLowerCase()
    if (!ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext))) {
      setError(`Unsupported file type. Allowed: ${ACCEPTED_EXTENSIONS.map((e) => e.slice(1).toUpperCase()).join(', ')}.`)
      return
    }
    if (candidate.size > MAX_UPLOAD_BYTES) {
      setError('File is larger than the 20 MiB upload limit.')
      return
    }
    setError('')
    setPreviewUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev)
      return URL.createObjectURL(candidate)
    })
    setFile(candidate)
  }, [])

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!file) {
      setError('Drop or choose a reference clip first.')
      return
    }
    if (!displayName.trim()) {
      setError('Give the cloned voice a name.')
      return
    }
    setError('')
    setCloning(true)
    try {
      const result = await api.cloneVoice(file, displayName.trim(), language)
      onCloned({ id: result.id, display_name: result.display_name })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Cloning failed. Try again.')
    } finally {
      setCloning(false)
    }
  }

  const onDrop = (e: React.DragEvent) => {
    e.preventDefault()
    setDragActive(false)
    acceptFile(e.dataTransfer.files?.[0])
  }

  return (
    <div className="modal-backdrop" onClick={cloning ? undefined : onClose}>
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="voice-clone-modal-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="voice-clone-head">
          <h3 id="voice-clone-modal-title">
            <Mic size={16} strokeWidth={2.4} className="voice-clone-head-icon" />
            Clone a voice
          </h3>
          <button
            type="button"
            className="btn btn-sm btn-icon"
            onClick={onClose}
            disabled={cloning}
            aria-label="Close voice cloning"
          >
            <X size={16} />
          </button>
        </div>
        <p className="muted voice-clone-hint">
          Upload a 3-10 second clip of the target voice (WAV, MP3 or M4A). We trim
          silence, match loudness, and register it as an approved custom voice.
        </p>

        <form onSubmit={(e) => void submit(e)}>
          <div
            className={`dropzone ${dragActive ? 'active' : ''} ${file ? 'has-file' : ''}`}
            role="button"
            tabIndex={0}
            aria-label="Choose or drop a reference audio clip"
            onClick={() => !cloning && inputRef.current?.click()}
            onKeyDown={(e) => {
              if ((e.key === 'Enter' || e.key === ' ') && !cloning) {
                e.preventDefault()
                inputRef.current?.click()
              }
            }}
            onDragOver={(e) => {
              e.preventDefault()
              if (!cloning) setDragActive(true)
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={onDrop}
          >
            <input
              ref={inputRef}
              type="file"
              accept={ACCEPTED_EXTENSIONS.join(',')}
              className="sr-only"
              onChange={(e) => acceptFile(e.target.files?.[0])}
              disabled={cloning}
            />
            <Upload size={22} strokeWidth={2} className="dropzone-icon" />
            {file ? (
              <p className="dropzone-file" title={`${file.name} · ${(file.size / 1024).toFixed(0)} KB`}>
                {file.name}
                <span className="muted"> · {(file.size / 1024).toFixed(0)} KB</span>
              </p>
            ) : (
              <p className="muted">Drop reference clip here, or click to browse</p>
            )}
          </div>

          {file && previewUrl && (
            <VoicePreviewBar
              name="Reference clip"
              pill="Uploaded"
              sampleSrc={previewUrl}
            />
          )}

          <div className="form-group" style={{ marginTop: '1rem' }}>
            <label htmlFor="clone-name">Voice name *</label>
            <input
              id="clone-name"
              type="text"
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="e.g. Morgan — podcast host"
              maxLength={200}
              disabled={cloning}
              required
            />
          </div>

          <div className="form-group">
            <label htmlFor="clone-language">Primary language</label>
            <select
              id="clone-language"
              value={language}
              onChange={(e) => setLanguage(e.target.value)}
              disabled={cloning}
            >
              {LANGUAGES.map((l) => (
                <option key={l} value={l}>{l}</option>
              ))}
            </select>
          </div>

          {cloning && (
            <div
              className="output-progress-track"
              role="progressbar"
              aria-label="Extracting voice clone"
              style={{ margin: '0.9rem 0 0.4rem' }}
            >
              <div className="output-progress-bar indeterminate" />
            </div>
          )}

          {error && (
            <div className="error-banner" role="alert" style={{ marginBottom: '0.9rem' }}>
              {error}
            </div>
          )}

          <div className="modal-actions">
            <button type="button" className="btn" onClick={onClose} disabled={cloning}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={cloning || !file}>
              {cloning ? 'Extracting…' : 'Extract & Clone Voice'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
