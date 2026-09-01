import { FileAudio } from 'lucide-react'
import { useState } from 'react'

export type ExportFormat = 'wav' | 'mp3'

const FORMATS: Array<{ value: ExportFormat; label: string; hint: string }> = [
  { value: 'wav', label: 'WAV', hint: 'Uncompressed high fidelity' },
  { value: 'mp3', label: 'MP3', hint: 'Compact universal audio' },
]

/**
 * Backend endpoint for multi-format downloads (Phase 5B). Default format is
 * WAV, which the endpoint streams byte-identical from the stored artifact.
 */
export function exportDownloadUrl(narrationId: string, format: ExportFormat): string {
  return `/api/audio/${narrationId}/download?format=${format}`
}

/**
 * Compact WAV | MP3 | FLAC export format selector with a download trigger.
 *
 * Default is WAV (uncompressed high fidelity); creators can switch to MP3 or
 * FLAC and the download link targets the chosen format. `compactLabel` keeps
 * the trigger text as plain "Download" (used in dense history rows); the
 * default renders the chosen format in the trigger ("Download WAV").
 */
export function ExportFormatSelector({
  narrationId,
  compactLabel = false,
}: {
  narrationId: string
  compactLabel?: boolean
}) {
  const [format, setFormat] = useState<ExportFormat>('wav')
  const active = FORMATS.find((f) => f.value === format) ?? FORMATS[0]
  const triggerText = compactLabel ? 'Download' : `Download ${active.label}`

  return (
    <div className="export-selector" role="group" aria-label="Export format">
      <div className="export-selector-options">
        {FORMATS.map((f) => (
          <button
            key={f.value}
            type="button"
            className={`export-option ${format === f.value ? 'active' : ''}`}
            onClick={() => setFormat(f.value)}
            aria-pressed={format === f.value}
            aria-label={`${f.label} export format — ${f.hint}`}
            title={f.hint}
          >
            {f.label}
          </button>
        ))}
      </div>
      <a
        className="export-download-btn"
        href={exportDownloadUrl(narrationId, format)}
        download
        aria-label={triggerText}
        title={`Download ${active.label} — ${active.hint}`}
      >
        <FileAudio size={14} strokeWidth={2} />
        {triggerText}
      </a>
    </div>
  )
}
