import { Pause, Play } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

// Natural voice-print static waveform (WhatsApp/Messenger style). Hand-tuned
// irregular heights — no repeating formula — mapping 1:1 to bar percentages.
const STATIC_BAR_HEIGHTS = [
  12, 20, 35, 50, 85, 40, 65, 90, 100, 75, 45, 30, 60, 80, 95, 70, 50, 85, 60,
  35, 75, 90, 40, 20, 55, 80, 65, 30, 45, 20, 12,
]
const BAR_COUNT = STATIC_BAR_HEIGHTS.length

/**
 * Active-voice preview bar: a clean Messenger/WhatsApp-style voice note
 * player. Static rounded bars fill teal behind the playhead and stay muted
 * obsidian ahead of it; clicking the waveform scrubs.
 *
 * Playback stays IDM-proof: the sample is fetched relative to the origin
 * (Vite proxy) as an ArrayBuffer, decoded with decodeAudioData(), and played
 * through an AudioBufferSourceNode — no AnalyserNode frequency loops, no
 * <audio src>, blob URLs, or object URLs anywhere.
 */
export function VoicePreviewBar({
  name,
  pill,
  sampleSrc,
}: {
  name: string
  pill: string
  sampleSrc: string | null
}) {
  const audioCtxRef = useRef<AudioContext | null>(null)
  const bufferRef = useRef<AudioBuffer | null>(null)
  const sourceRef = useRef<AudioBufferSourceNode | null>(null)
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const startedAtRef = useRef(0)
  const offsetRef = useRef(0)

  const [playing, setPlaying] = useState(false)
  const [progress, setProgress] = useState(0) // 0..1
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)

  const ensureContext = useCallback(() => {
    if (!audioCtxRef.current) {
      const Ctx: typeof AudioContext =
        window.AudioContext ??
        (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      audioCtxRef.current = new Ctx()
    }
    return audioCtxRef.current
  }, [])

  const stopTimer = useCallback(() => {
    if (timerRef.current !== null) {
      clearInterval(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const stopSource = useCallback(() => {
    stopTimer()
    if (sourceRef.current) {
      const source = sourceRef.current
      sourceRef.current = null
      source.onended = null
      try {
        source.stop()
      } catch {
        // already stopped
      }
      source.disconnect()
    }
  }, [stopTimer])

  const startPlayback = useCallback(
    async (fromOffset: number) => {
      const ctx = ensureContext()
      if (ctx.state === 'suspended') await ctx.resume()
      const buffer = bufferRef.current
      if (!buffer) return
      stopSource()
      const source = ctx.createBufferSource()
      source.buffer = buffer
      source.connect(ctx.destination) // pure in-memory PCM → speakers
      source.onended = () => {
        if (sourceRef.current !== source) return // manual stop, not natural end
        sourceRef.current = null
        stopTimer()
        offsetRef.current = 0
        setProgress(0)
        setPlaying(false)
      }
      source.start(0, Math.max(0, Math.min(fromOffset, buffer.duration)))
      sourceRef.current = source
      startedAtRef.current = ctx.currentTime - fromOffset
      setPlaying(true)
      // Light playhead tracker — only divides two clock values, so the bar
      // fill advances smoothly with zero per-frame audio processing.
      timerRef.current = setInterval(() => {
        const c = audioCtxRef.current
        const buf = bufferRef.current
        if (!c || !buf) return
        setProgress(Math.min(1, (c.currentTime - startedAtRef.current) / buf.duration))
      }, 50)
    },
    [ensureContext, stopSource, stopTimer],
  )

  const pause = useCallback(() => {
    const ctx = audioCtxRef.current
    if (ctx && bufferRef.current) {
      offsetRef.current = Math.max(
        0,
        Math.min(ctx.currentTime - startedAtRef.current, bufferRef.current.duration),
      )
    }
    stopSource()
    setPlaying(false)
  }, [stopSource])

  const toggle = useCallback(async () => {
    const ctx = ensureContext()
    if (ctx.state === 'suspended') {
      await ctx.resume()
    }
    if (playing) {
      pause()
      return
    }
    await startPlayback(offsetRef.current)
  }, [ensureContext, pause, playing, startPlayback])

  const seek = useCallback(
    async (ratio: number) => {
      const buffer = bufferRef.current
      if (!buffer) return
      const clamped = Math.min(1, Math.max(0, ratio))
      const target = clamped * buffer.duration
      setProgress(clamped)
      if (playing) {
        await startPlayback(target)
      } else {
        offsetRef.current = target
      }
    },
    [playing, startPlayback],
  )

  const onWaveformClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      const rect = e.currentTarget.getBoundingClientRect()
      if (rect.width === 0) return
      void seek((e.clientX - rect.left) / rect.width)
    },
    [seek],
  )

  // Voice selection changed: tear down playback, drop the decoded buffer,
  // and prefetch + decode the new sample into memory (IDM-safe).
  useEffect(() => {
    let cancelled = false
    stopSource()
    bufferRef.current = null
    offsetRef.current = 0
    setPlaying(false)
    setProgress(0)
    setFailed(false)

    if (!sampleSrc) return
    const load = async () => {
      try {
        setLoading(true)
        const response = await fetch(sampleSrc, {
          headers: { Accept: 'audio/wav' },
          credentials: 'same-origin',
        })
        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        const arrayBuffer = await response.arrayBuffer()
        if (cancelled) return
        const ctx = ensureContext()
        const audioBuffer = await ctx.decodeAudioData(arrayBuffer)
        if (cancelled) return
        bufferRef.current = audioBuffer
      } catch {
        // Graceful failure only: no direct URL, blob, object URL, or DOM
        // audio element is ever presented to download managers.
        if (!cancelled) setFailed(true)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [ensureContext, sampleSrc, stopSource])

  // Unmount: stop playback and release the AudioContext.
  useEffect(() => {
    const ctx = audioCtxRef.current
    return () => {
      stopSource()
      ctx?.close().catch(() => {})
      audioCtxRef.current = null
      bufferRef.current = null
    }
  }, [stopSource])

  const ready = bufferRef.current !== null
  const playedBars = Math.round(progress * BAR_COUNT)

  return (
    <div className="voice-preview-bar" role="group" aria-label={`Active voice preview: ${name}`}>
      <div className="voice-preview-info">
        <span className="voice-preview-name">{name}</span>
        <span className="voice-preview-pill">{pill}</span>
      </div>
      <div className="voice-preview-player">
        <button
          type="button"
          className="voice-preview-play"
          onClick={() => void toggle()}
          disabled={loading || failed || !ready}
          aria-label={playing ? `Pause ${name} preview` : `Play ${name} preview`}
          title={
            loading
              ? 'Fetching voice sample…'
              : failed
                ? 'Preview unavailable'
                : playing
                  ? 'Pause preview'
                  : 'Play preview'
          }
        >
          {playing ? <Pause size={14} strokeWidth={2.5} /> : <Play size={14} strokeWidth={2.5} />}
        </button>
        <div
          className="voice-waveform"
          role="slider"
          aria-label={`Seek ${name} preview`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(progress * 100)}
          tabIndex={ready ? 0 : -1}
          onClick={onWaveformClick}
          onKeyDown={(e) => {
            const buffer = bufferRef.current
            if (!buffer) return
            if (e.key === 'ArrowRight') void seek(Math.min(1, progress + 20 / buffer.duration))
            if (e.key === 'ArrowLeft') void seek(Math.max(0, progress - 20 / buffer.duration))
          }}
        >
          {STATIC_BAR_HEIGHTS.map((h, i) => (
            <span
              key={i}
              className={`waveform-bar ${i < playedBars ? 'played' : ''}`}
              style={{ height: `${h}%` }}
            />
          ))}
        </div>
        {loading && <span className="voice-preview-loading">Fetching voice sample…</span>}
        {failed && <span className="voice-preview-error">Preview unavailable</span>}
      </div>
    </div>
  )
}
