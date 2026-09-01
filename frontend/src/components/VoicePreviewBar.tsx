import { Pause, Play } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

const BARS = 32 // analyser.fftSize = 64 → 32 frequency bins

// Human speech energy concentrates in the low/mid bins: with analyser.fftSize
// = 64 every bin spans sampleRate/64 Hz (≈375 Hz at 24 kHz), so the voice
// band (80 Hz–4 kHz, fundamentals + formants) lives in the bottom third of
// the spectrum and the remaining bins are mostly empty. The visualizer maps
// bars logarithmically across the spectrum and boosts low/mid bins so spoken
// syllables drive the bars to the full 90–100 % range, while silence falls to
// the 2 px CSS baseline.
function binForBar(i: number, total: number): number {
  const t = i / (total - 1)
  return Math.min(total - 1, Math.round(Math.pow(t, 1.7) * (total - 1)))
}

function speechEmphasis(bin: number, total: number): number {
  // ~1.85× gain on the speech-fundamental bins, tapering to ~1.0× on the
  // sparse high-frequency tail.
  return Math.max(1.0, 1.9 - 1.05 * (bin / total))
}

function scaleLevel(rawByte: number, emphasis: number): number {
  const value = Math.min(255, rawByte * emphasis)
  // Spec curve: non-linear (value/255)^0.75 × 120, capped at 100 %.
  return Math.min(100, Math.pow(value / 255, 0.75) * 120)
}

/**
 * Active-voice preview bar (Phase 6B): compact obsidian card with the voice
 * name/language pill and a real-time Web Audio equalizer.
 *
 * IDM proofing: audio is fetched with credentials → ArrayBuffer →
 * decodeAudioData() and played as PCM through an AudioBufferSourceNode routed
 * source → analyser → destination. Media never touches a DOM media element or
 * a direct URL, so download managers cannot intercept the stream.
 *
 * Visualizer: a requestAnimationFrame loop reads getByteFrequencyData() and
 * maps each frequency bin (0–255) to a bar height percentage, so the bars
 * pulse strictly with the voice's actual pitch, loudness, and cadence — and
 * fall completely flat during pauses.
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
  const analyserRef = useRef<AnalyserNode | null>(null)
  const bufferRef = useRef<AudioBuffer | null>(null)
  const sourceRef = useRef<AudioBufferSourceNode | null>(null)
  const rafRef = useRef<number | null>(null)
  const startedAtRef = useRef(0)
  const offsetRef = useRef(0)
  const freqDataRef = useRef<Uint8Array<ArrayBuffer>>(new Uint8Array(BARS))

  const [levels, setLevels] = useState<number[]>(() => new Array<number>(BARS).fill(0))
  const [playing, setPlaying] = useState(false)
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)

  const ensureContext = useCallback(() => {
    if (!audioCtxRef.current) {
      const Ctx: typeof AudioContext =
        window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext
      const ctx = new Ctx()
      const analyser = ctx.createAnalyser()
      analyser.fftSize = 64 // Yields 32 frequency bins
      analyser.smoothingTimeConstant = 0.72
      analyser.connect(ctx.destination)
      audioCtxRef.current = ctx
      analyserRef.current = analyser
      freqDataRef.current = new Uint8Array(analyser.frequencyBinCount)
    }
    return audioCtxRef.current
  }, [])

  const stopSource = useCallback(() => {
    if (rafRef.current !== null) {
      cancelAnimationFrame(rafRef.current)
      rafRef.current = null
    }
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
  }, [])

  const tick = useCallback(() => {
    const analyser = analyserRef.current
    if (!analyser) return
    analyser.getByteFrequencyData(freqDataRef.current)
    const data = freqDataRef.current
    const total = data.length
    const next = new Array<number>(total)
    for (let i = 0; i < total; i++) {
      const bin = binForBar(i, total)
      next[i] = scaleLevel(data[bin], speechEmphasis(bin, total))
    }
    setLevels(next)
    rafRef.current = requestAnimationFrame(tick)
  }, [])

  const startPlayback = useCallback(
    async (fromOffset: number) => {
      const ctx = ensureContext()
      if (ctx.state === 'suspended') await ctx.resume()
      const buffer = bufferRef.current
      const analyser = analyserRef.current
      if (!buffer || !analyser) return
      stopSource()
      const source = ctx.createBufferSource()
      source.buffer = buffer
      source.connect(analyser) // Web Audio graph: source → analyser → destination
      source.onended = () => {
        if (sourceRef.current !== source) return // manual stop, not natural end
        sourceRef.current = null
        if (rafRef.current !== null) {
          cancelAnimationFrame(rafRef.current)
          rafRef.current = null
        }
        offsetRef.current = 0
        setPlaying(false)
        setLevels(new Array<number>(BARS).fill(0))
      }
      source.start(0, Math.max(0, Math.min(fromOffset, buffer.duration)))
      sourceRef.current = source
      startedAtRef.current = ctx.currentTime - fromOffset
      setPlaying(true)
      rafRef.current = requestAnimationFrame(tick)
    },
    [ensureContext, stopSource, tick],
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
    setLevels(new Array<number>(BARS).fill(0))
  }, [stopSource])

  const toggle = useCallback(async () => {
    // Always resume the AudioContext on the user-gesture click. Browsers
    // create AudioContexts in 'suspended' state and require a gesture before
    // analyser data flows — without this the equalizer would never pulse in
    // sync with the voice.
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

  // Voice selection changed: tear down playback, drop the decoded buffer,
  // and prefetch + decode the new sample into memory (IDM-safe).
  useEffect(() => {
    let cancelled = false
    stopSource()
    bufferRef.current = null
    offsetRef.current = 0
    setPlaying(false)
    setFailed(false)
    setLevels(new Array<number>(BARS).fill(0))

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
        // Graceful failure: no direct URL, blob, object URL, or DOM audio
        // element is ever appended; the preview bar simply shows the
        // "Preview unavailable" state.
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
      analyserRef.current = null
      bufferRef.current = null
    }
  }, [stopSource])

  const ready = bufferRef.current !== null

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
          className={`waveform-bars ${playing ? 'playing' : ''}`}
          role="img"
          aria-label={playing ? 'Preview waveform reacting to audio' : 'Preview waveform idle'}
        >
          {levels.map((level, i) => (
            <span
              key={i}
              className="waveform-bar"
              style={{ height: `${level}%` }}
            />
          ))}
        </div>
        {loading && <span className="voice-preview-loading">Fetching voice sample…</span>}
        {failed && <span className="voice-preview-error">Preview unavailable</span>}
      </div>
    </div>
  )
}
