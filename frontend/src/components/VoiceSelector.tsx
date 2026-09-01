import { useEffect, useMemo, useRef, useState } from 'react'
import { Check, ChevronDown, Clock, Mic2, Search, Sparkles, Users } from 'lucide-react'

export interface VoiceOption {
  kind: 'builtin' | 'custom'
  id: string
  name: string
  language: string
  description: string
}

/**
 * Searchable categorized voice dropdown (Phase 6A).
 *
 * Groups: Built-in Voices, Approved Custom Voices (dynamic), and a disabled
 * "Voice Clone (Coming Soon)" teaser. Includes a search input and closes on
 * outside click / Escape.
 */
export function VoiceSelector({
  options,
  value,
  onChange,
  disabled = false,
}: {
  options: VoiceOption[]
  value: string
  onChange: (id: string) => void
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const rootRef = useRef<HTMLDivElement | null>(null)
  const searchRef = useRef<HTMLInputElement | null>(null)

  const selected = options.find((o) => o.id === value)

  useEffect(() => {
    if (!open) return
    const onPointerDown = (e: MouseEvent | TouchEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('mousedown', onPointerDown)
    document.addEventListener('touchstart', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    // Focus the search field on open for immediate typing.
    searchRef.current?.focus()
    return () => {
      document.removeEventListener('mousedown', onPointerDown)
      document.removeEventListener('touchstart', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [open])

  const q = query.trim().toLowerCase()
  const builtinMatches = useMemo(
    () => options.filter((o) => o.kind === 'builtin' && (o.name.toLowerCase().includes(q) || o.language.toLowerCase().includes(q))),
    [options, q],
  )
  const customMatches = useMemo(
    () => options.filter((o) => o.kind === 'custom' && (o.name.toLowerCase().includes(q) || o.language.toLowerCase().includes(q))),
    [options, q],
  )
  const cloneTeaserVisible = q === '' || 'clone voice'.includes(q)

  return (
    <div className="voice-select" ref={rootRef}>
      <button
        type="button"
        className="voice-select-trigger"
        onClick={() => setOpen((prev) => !prev)}
        disabled={disabled}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Active voice"
      >
        <Mic2 size={15} strokeWidth={2.2} className="voice-select-trigger-icon" />
        <span className="voice-select-trigger-name">{selected?.name ?? 'Choose a voice'}</span>
        <span className="voice-select-trigger-pill">{selected?.language ?? ''}</span>
        <ChevronDown size={15} className={`voice-select-chevron ${open ? 'open' : ''}`} />
      </button>

      {open && (
        <div className="voice-select-panel" role="listbox" aria-label="Voice options">
          <div className="voice-select-search">
            <Search size={14} strokeWidth={2.2} />
            <input
              ref={searchRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search voices…"
              aria-label="Search voices"
            />
          </div>

          <div className="voice-select-list">
            {builtinMatches.length > 0 && (
              <>
                <div className="voice-select-group">
                  <Users size={12} strokeWidth={2.4} />
                  Built-in Voices
                </div>
                {builtinMatches.map((o) => (
                  <button
                    key={o.id}
                    type="button"
                    role="option"
                    aria-selected={o.id === value}
                    className={`voice-select-option ${o.id === value ? 'selected' : ''}`}
                    onClick={() => {
                      onChange(o.id)
                      setOpen(false)
                      setQuery('')
                    }}
                  >
                    <span className="voice-select-option-name">{o.name}</span>
                    <span className="voice-select-option-meta">{o.language}</span>
                    {o.id === value && <Check size={14} strokeWidth={2.6} className="voice-select-check" />}
                  </button>
                ))}
              </>
            )}

            {customMatches.length > 0 && (
              <>
                <div className="voice-select-group">
                  <Sparkles size={12} strokeWidth={2.4} />
                  Approved Custom Voices
                </div>
                {customMatches.map((o) => (
                  <button
                    key={o.id}
                    type="button"
                    role="option"
                    aria-selected={o.id === value}
                    className={`voice-select-option ${o.id === value ? 'selected' : ''}`}
                    onClick={() => {
                      onChange(o.id)
                      setOpen(false)
                      setQuery('')
                    }}
                  >
                    <span className="voice-select-option-name">{o.name}</span>
                    <span className="voice-select-option-meta">Custom · {o.language}</span>
                    {o.id === value && <Check size={14} strokeWidth={2.6} className="voice-select-check" />}
                  </button>
                ))}
              </>
            )}

            {builtinMatches.length === 0 && customMatches.length === 0 && !cloneTeaserVisible && (
              <p className="voice-select-empty">No voices match “{query}”.</p>
            )}

            {cloneTeaserVisible && (
              <>
                <div className="voice-select-group">
                  <Clock size={12} strokeWidth={2.4} />
                  Voice Clone
                </div>
                <div className="voice-select-option disabled" role="option" aria-selected={false} aria-disabled="true">
                  <span className="voice-select-option-name">Voice Clone (Coming Soon)</span>
                  <span className="voice-select-soon-badge">Soon</span>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
