import { useCallback, useRef } from 'react'

export function useInsertSpeakerTag(
  onInsert: (tag: string) => void,
) {
  const selectRef = useRef<HTMLSelectElement>(null)

  const insertAtCursor = useCallback(
    (textarea: HTMLTextAreaElement, tag: string) => {
      const start = textarea.selectionStart ?? 0
      const end = textarea.selectionEnd ?? 0
      const before = textarea.value.slice(0, start)
      const after = textarea.value.slice(end)
      const separator = before.length > 0 && !before.endsWith(" ") && !before.endsWith("\n") ? " " : ""
      const newValue = `${before}${separator}${tag}${after}`
      onInsert(newValue)
      // Restore cursor to just after the inserted tag.
      requestAnimationFrame(() => {
        const newPos = (before + separator + tag).length
        textarea.setSelectionRange(newPos, newPos)
        textarea.focus()
      })
    },
    [onInsert],
  )

  const handleInsertSpeaker = useCallback(
    (textarea: HTMLTextAreaElement) => {
      const select = selectRef.current
      if (!select) return
      const speaker = select.value
      if (!speaker) return
      const tag = `[Speaker: ${speaker}]`
      insertAtCursor(textarea, tag)
      select.value = ""
    },
    [insertAtCursor],
  )

  return { selectRef, handleInsertSpeaker }
}
