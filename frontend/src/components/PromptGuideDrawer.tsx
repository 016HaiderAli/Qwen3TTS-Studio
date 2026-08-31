import { useState, useCallback } from 'react'
import { Copy, Check, X } from 'lucide-react'

interface PromptTag {
  tag: string
  description: string
}

interface TagCategory {
  title: string
  tags: PromptTag[]
}

const TAG_CATEGORIES: TagCategory[] = [
  {
    title: 'Delivery Styles',
    tags: [
      { tag: '[Whisper]', description: 'Soft, breathy speech as if speaking secrets' },
      { tag: '[Dramatic]', description: 'Heightened emotion and theatrical delivery' },
      { tag: '[Fast-paced]', description: 'Quick, energetic speech with urgency' },
      { tag: '[Calm Narrator]', description: 'Slow, measured, reassuring narration tone' },
    ],
  },
  {
    title: 'Expressive SFX',
    tags: [
      { tag: '[Breather]', description: 'Add a subtle breath sound between words' },
      { tag: '[Heavy Breathing]', description: 'Audible heavy breathing effect' },
      { tag: '[Sigh]', description: 'Include an audible sigh in the delivery' },
      { tag: '[Laughter]', description: 'Brief laughing sound or chuckling' },
    ],
  },
  {
    title: 'Timing & Pauses',
    tags: [
      { tag: '[Pause: 0.5s]', description: 'Short half-second pause' },
      { tag: '[Pause: 1s]', description: 'One second pause for emphasis' },
      { tag: '[Pause: 2s]', description: 'Longer two-second pause' },
    ],
  },
]

interface PromptGuideDrawerProps {
  isOpen: boolean
  onClose: () => void
  onInsert: (tag: string) => void
}

export function PromptGuideDrawer({ isOpen, onClose, onInsert }: PromptGuideDrawerProps) {
  const [copiedTag, setCopiedTag] = useState<string | null>(null)

  const handleCopy = useCallback(async (tag: string) => {
    await navigator.clipboard.writeText(tag)
    setCopiedTag(tag)
    setTimeout(() => setCopiedTag(null), 1500)
  }, [])

  const handleInsert = useCallback((tag: string) => {
    onInsert(tag)
    onClose()
  }, [onInsert, onClose])

  if (!isOpen) return null

  return (
    <>
      <div
        className="modal-backdrop"
        onClick={onClose}
        role="presentation"
      />
      <div
        className="prompt-guide-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Prompt Helper Guide"
      >
        <div className="prompt-guide-header">
          <h2>Prompt Helper / Tag Guide</h2>
          <button
            type="button"
            className="btn btn-sm btn-icon"
            onClick={onClose}
            aria-label="Close prompt guide"
          >
            <X size={18} />
          </button>
        </div>
        <div className="prompt-guide-content">
          {TAG_CATEGORIES.map((category) => (
            <div key={category.title} className="prompt-guide-category">
              <h3>{category.title}</h3>
              <div className="prompt-guide-tags">
                {category.tags.map((item) => (
                  <div key={item.tag} className="prompt-guide-tag-item">
                    <div className="prompt-guide-tag-info">
                      <code className="prompt-guide-tag-label">{item.tag}</code>
                      <span className="prompt-guide-tag-desc">{item.description}</span>
                    </div>
                    <div className="prompt-guide-tag-actions">
                      <button
                        type="button"
                        className="btn btn-sm"
                        onClick={() => handleCopy(item.tag)}
                        aria-label={`Copy ${item.tag}`}
                      >
                        {copiedTag === item.tag ? (
                          <>
                            <Check size={12} />
                            Copied!
                          </>
                        ) : (
                          <>
                            <Copy size={12} />
                            Copy
                          </>
                        )}
                      </button>
                      <button
                        type="button"
                        className="btn btn-sm btn-primary"
                        onClick={() => handleInsert(item.tag)}
                        aria-label={`Insert ${item.tag}`}
                      >
                        Insert
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
        <div className="prompt-guide-footer">
          <p className="muted">
            Add tags directly in your script to control delivery, pauses, and expressive effects.
          </p>
        </div>
      </div>
    </>
  )
}
