import { useCallback, useEffect, useRef, useState } from 'react'
import { Upload, X, Mic, Square, RotateCcw } from 'lucide-react'
import { api, ApiError } from '../api'
import { VoicePreviewBar } from './VoicePreviewBar'

const MAX_UPLOAD_BYTES = 20 * 1024 * 1024 // 20 MiB, matches backend limit
const ACCEPTED_EXTENSIONS = ['.wav', '.mp3', '.m4a', '.ogg']
const RECORDING_MIME = 'audio/webm'
const RECORDING_EXTENSION = '.webm'
const MIN_GUIDE_SECONDS = 3
const MAX_RECORD_SECONDS = 30

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

type InputTab = 'upload' | 'record'

/**
 * Phase 7A voice-clone modal, Phase 8 extended: dual input tabs.
 *
 * - "Upload Audio": drag & drop / browse for a WAV/MP3/M4A/OGG clip (existing).
 * - "Record Microphone": in-browser MediaRecorder capture with a live duration
 *   timer, auto-stop at 30 s, preview playback and re-record.
 *
 * Both tabs feed the same reference-clip state, previewed through the shared
 * waveform player. An editable reference transcript (embedding guidance for
 * Qwen — never spoken) defaults to a greeting using the voice name.
 */
export function VoiceCloneModal({
  onClose,
  onCloned,
}: {
  onClose: () => void
  onCloned: (result: { id: string; display_name: string }) => void
}) {
  const [tab, setTab] = useState<InputTab>('upload')
  const [file, setFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [displayName, setDisplayName] = useState('')
  const [referenceText, setReferenceText] = useState('')
  const [transcriptTouched, setTranscriptTouched] = useState(false)
  const [language, setLanguage] = useState('English')
  const [error, setError] = useState('')
  const [cloning, setCloning] = useState(false)
  const [dragActive, setDragActive] = useState(false)
  const inputRef = useRef<HTMLInputElement | null>(null)

  // --- Recording state ---
  const [recording, setRecording] = useState(false)
  const [recordSeconds, setRecordSeconds] = useState(0)
  const recorderRef = useRef<MediaRecorder | null>(null)
  const chunksRef = useRef<Blob[]>([])
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const streamRef = useRef<MediaStream | null>(null)

  // Revoke the previous object URL whenever the clip changes or modal unmounts.
  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl)
    }
  }, [previewUrl])

  // Full cleanup on unmount: stop mic, timers, and recorder.
  useEffect(() => {
    return () => {
      stopRecording(false)
      if (timerRef.current !== null) {
        clearInterval(timerRef.current)
        timerRef.current = null
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Default transcript follows the voice name until the user edits it.
  useEffect(() => {
    if (!transcriptTouched) {
      const trimmed = displayName.trim()
      setReferenceText(
        trimmed
          ? `Hello, I am ${trimmed}! It's a pleasure to meet you.`
          : '',
      )
    }
  }, [displayName, transcriptTouched])

  const setClip = useCallback((candidate: File | null) => {
    setError('')
    setPreviewUrl((prev) => {
      if (prev) URL.revokeObjectURL(prev)
      return candidate ? URL.createObjectURL(candidate) : null
    })
    setFile(candidate)
  }, [])

  const acceptFile = useCallback(
    (candidate: File | undefined | null) => {
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
      setClip(candidate)
    },
    [setClip],
  )

  // --- Microphone recording (MediaRecorder) ---

  const stopRecording = useCallback((keep: boolean) => {
    if (timerRef.current !== null) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
    const recorder = recorderRef.current
    if (recorder && recorder.state !== 'inactive') {
      // onstop below finalizes the File when `keep` is true.
      (recorder as MediaRecorder & { __keep?: boolean }).__keep = keep
      recorder.stop()
    } else if (!keep) {
      recorderRef.current = null
    }
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    setRecording(false)
  }, [])

  const startRecording = async () => {
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setError('Audio recording is not supported in this browser. Use the upload tab instead.')
      return
    }
    try {
      setError('')
      // Discard any previously selected clip when starting fresh.
      setClip(null)
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      streamRef.current = stream
      const recorder = new MediaRecorder(stream, { mimeType: RECORDING_MIME })
      chunksRef.current = []
      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data)
      }
      recorder.onstop = () => {
        const keep = (recorder as MediaRecorder & { __keep?: boolean }).__keep !== false
        if (keep && chunksRef.current.length > 0) {
          const blob = new Blob(chunksRef.current, { type: RECORDING_MIME })
          const recorded = new File([blob], `reference${RECORDING_EXTENSION}`, {
            type: RECORDING_MIME,
          })
          setClip(recorded)
        }
        recorderRef.current = null
      }
      recorder.start()
      recorderRef.current = recorder
      setRecording(true)
      setRecordSeconds(0)
      timerRef.current = setInterval(() => {
        setRecordSeconds((prev) => {
          if (prev + 1 >= MAX_RECORD_SECONDS) {
            // Auto-stop at the 30 s guide ceiling.
            stopRecording(true)
            return MAX_RECORD_SECONDS
          }
          return prev + 1
        })
      }, 1000)
    } catch {
      setError('Microphone access was denied. Allow it or use the upload tab.')
      streamRef.current?.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
  }

  const submit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!file) {
      setError('Provide a reference clip first (upload or record).')
      return
    }
    if (!displayName.trim()) {
      setError('Give the cloned voice a name.')
      return
    }
    setError('')
    setCloning(true)
    try {
      const result = await api.cloneVoice(
        file,
        displayName.trim(),
        language,
        referenceText.trim(),
      )
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

  const recordingTooShort = !recording && recordSeconds > 0 && recordSeconds < MIN_GUIDE_SECONDS

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
            onClick={() => {
              stopRecording(false)
              onClose()
            }}
            disabled={cloning}
            aria-label="Close voice cloning"
          >
            <X size={16} />
          </button>
        </div>
        <p className="muted voice-clone-hint">
          Provide a 3-10 second clip of the target voice — upload a file or record
          straight from your microphone. We trim silence, match loudness, and
          register the voice as an approved custom voice.
        </p>

        <form onSubmit={(e) => void submit(e)}>
          <div className="clone-tabs" role="tablist" aria-label="Reference clip input method">
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'upload'}
              className={`clone-tab ${tab === 'upload' ? 'active' : ''}`}
              onClick={() => !cloning && !recording && setTab('upload')}
            >
              <Upload size={13} strokeWidth={2.2} />
              Upload Audio
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={tab === 'record'}
              className={`clone-tab ${tab === 'record' ? 'active' : ''}`}
              onClick={() => !cloning && !recording && setTab('record')}
            >
              <Mic size={13} strokeWidth={2.2} />
              Record Microphone
            </button>
          </div>

          {tab === 'upload' ? (
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
          ) : (
            <div className={`record-panel ${recording ? 'recording' : ''}`}>
              {recording ? (
                <>
                  <button
                    type="button"
                    className="record-btn stop"
                    onClick={() => stopRecording(true)}
                    aria-label="Stop recording"
                    title="Stop recording"
                  >
                    <Square size={18} strokeWidth={2.4} />
                  </button>
                  <div className="record-timer" role="timer" aria-live="off">
                    <span className="record-dot" aria-hidden="true" />
                    {String(Math.floor(recordSeconds / 60)).padStart(2, '0')}:
                    {String(recordSeconds % 60).padStart(2, '0')}
                    <span className="muted record-guide"> / {MAX_RECORD_SECONDS}s</span>
                  </div>
                  <span className="muted record-hint">
                    {recordSeconds < MIN_GUIDE_SECONDS
                      ? `Keep going — aim for at least ${MIN_GUIDE_SECONDS}s of natural speech`
                      : 'Sounds good — stop when you are done'}
                  </span>
                </>
              ) : (
                <>
                  <button
                    type="button"
                    className="record-btn"
                    onClick={() => void startRecording()}
                    aria-label="Start recording"
                    title="Start recording"
                  >
                    <Mic size={18} strokeWidth={2.4} />
                  </button>
                  <span className="muted record-hint">
                    Record {MIN_GUIDE_SECONDS}-{MAX_RECORD_SECONDS} seconds of natural speech
                  </span>
                </>
              )}
            </div>
          )}

          {file && previewUrl && (
            <div className="record-preview">
              <VoicePreviewBar
                name="Reference clip"
                pill={file.name.endsWith(RECORDING_EXTENSION) ? 'Recorded' : 'Uploaded'}
                sampleSrc={previewUrl}
              />
              {file.name.endsWith(RECORDING_EXTENSION) && !cloning && (
                <button
                  type="button"
                  className="tool-btn record-redo"
                  onClick={() => {
                    setClip(null)
                    setTab('record')
                  }}
                  aria-label="Discard recording and record again"
                >
                  <RotateCcw size={13} strokeWidth={2.2} />
                  Re-record
                </button>
              )}
            </div>
          )}

          {recordingTooShort && (
            <p className="muted record-warn" role="status">
              The clip is shorter than {MIN_GUIDE_SECONDS}s — record a little more for a better clone.
            </p>
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
            <label htmlFor="clone-transcript">
              Reference transcript{' '}
              <span className="field-hint inline">
                optional — what the clip says; improves cloning accuracy, never spoken
              </span>
            </label>
            <input
              id="clone-transcript"
              type="text"
              value={referenceText}
              onChange={(e) => {
                setTranscriptTouched(true)
                setReferenceText(e.target.value)
              }}
              maxLength={2000}
              disabled={cloning}
              placeholder="Transcribe the reference clip (optional)"
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
