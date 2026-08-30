export interface DialogueSegment {
  speaker: string
  text: string
  instruct?: string
}

const SPEAKER_COLORS: Record<string, string> = {
  Ryan: '#3b82f6',
  Serena: '#a855f7',
  Alex: '#10b981',
  Maya: '#f59e0b',
  Wei: '#ef4444',
  Sofia: '#06b6d4',
  Liam: '#f97316',
  Zoe: '#ec4899',
  Max: '#8b5cf6',
}

const DEFAULT_COLOR = '#6b7280'

export function speakerColor(speaker: string): string {
  return SPEAKER_COLORS[speaker] ?? DEFAULT_COLOR
}

interface DialogueSegmentDisplayProps {
  segments: DialogueSegment[]
}

export function DialogueSegmentDisplay({ segments }: DialogueSegmentDisplayProps) {
  return (
    <div className="dialogue-segments">
      {segments.map((seg, i) => {
        const color = speakerColor(seg.speaker)
        return (
          <div key={i} className="dialogue-segment-row">
            <span
              className="dialogue-speaker-badge"
              style={{ backgroundColor: color }}
            >
              {seg.speaker}
            </span>
            <span className="dialogue-segment-text">
              {seg.text}
              {seg.instruct && (
                <em className="dialogue-segment-instruct"> [{seg.instruct}]</em>
              )}
            </span>
          </div>
        )
      })}
    </div>
  )
}
