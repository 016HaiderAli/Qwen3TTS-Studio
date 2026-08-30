import { Download, Pause, Play, Volume2, VolumeX } from 'lucide-react'
import { useEffect, useRef, useState, type CSSProperties } from 'react'

function formatTime(seconds: number | null): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return '--:--'
  const total = Math.round(seconds)
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

function downloadUrl(src: string): string {
  return src.includes('?') ? `${src}&download=true` : `${src}?download=true`
}

export function AudioPlayer({ src, title }: { src: string; title?: string }) {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const [ready, setReady] = useState(false)
  const [failed, setFailed] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [currentTime, setCurrentTime] = useState(0)
  const [duration, setDuration] = useState<number | null>(null)
  const [volume, setVolume] = useState(1)
  const [muted, setMuted] = useState(false)
  const label = title ?? 'audio'

  useEffect(() => {
    const audio = audioRef.current
    if (!audio) return
    const onLoaded = () => {
      setFailed(false)
      setReady(true)
      if (Number.isFinite(audio.duration)) setDuration(audio.duration)
    }
    const onTime = () => setCurrentTime(audio.currentTime)
    const onPlay = () => setPlaying(true)
    const onPause = () => setPlaying(false)
    const onEnded = () => setPlaying(false)
    const onError = () => {
      setFailed(true)
      setPlaying(false)
    }
    audio.addEventListener('loadedmetadata', onLoaded)
    audio.addEventListener('timeupdate', onTime)
    audio.addEventListener('play', onPlay)
    audio.addEventListener('pause', onPause)
    audio.addEventListener('ended', onEnded)
    audio.addEventListener('error', onError)
    return () => {
      audio.removeEventListener('loadedmetadata', onLoaded)
      audio.removeEventListener('timeupdate', onTime)
      audio.removeEventListener('play', onPlay)
      audio.removeEventListener('pause', onPause)
      audio.removeEventListener('ended', onEnded)
      audio.removeEventListener('error', onError)
    }
  }, [])

  useEffect(() => {
    setReady(false)
    setFailed(false)
    setPlaying(false)
    setCurrentTime(0)
    setDuration(null)
  }, [src])

  const togglePlay = async () => {
    const audio = audioRef.current
    if (!audio) return
    if (audio.paused) {
      try {
        await audio.play()
        setPlaying(true)
      } catch {
        setPlaying(false)
      }
    } else {
      audio.pause()
      setPlaying(false)
    }
  }

  const seek = (value: number) => {
    const audio = audioRef.current
    if (!audio) return
    audio.currentTime = value
    setCurrentTime(value)
  }

  const changeVolume = (value: number) => {
    const audio = audioRef.current
    if (audio) {
      audio.volume = value
      audio.muted = false
    }
    setVolume(value)
    setMuted(false)
  }

  const toggleMute = () => {
    const audio = audioRef.current
    const next = !muted
    if (audio) audio.muted = next
    setMuted(next)
  }

  const enabled = ready && !failed
  const max = enabled ? (duration ?? 0) : 0
  const value = enabled && duration ? Math.min(currentTime, duration) : 0
  const pct =
    enabled && duration && duration > 0
      ? Math.min(100, (currentTime / duration) * 100)
      : 0

  return (
    <div className="audio-player" role="group" aria-label={`Audio player: ${label}`}>
      <audio ref={audioRef} src={src} preload="metadata" className="audio-source" />
      <div className="audio-player-main">
        <button
          type="button"
          className="audio-icon-btn"
          onClick={() => void togglePlay()}
          disabled={!enabled}
          aria-label={playing ? 'Pause' : 'Play'}
          title={playing ? 'Pause' : 'Play'}
        >
          {playing ? <Pause size={14} strokeWidth={2.5} /> : <Play size={14} strokeWidth={2.5} />}
        </button>
        <input
          type="range"
          className="audio-seek"
          min={0}
          max={max}
          step="any"
          value={value}
          onChange={(e) => seek(Number(e.target.value))}
          disabled={!enabled}
          style={{ '--audio-fill': `${pct}%` } as CSSProperties}
          aria-label="Seek"
          aria-valuetext={
            enabled ? `${formatTime(currentTime)} of ${formatTime(duration)}` : undefined
          }
        />
        <span className="audio-time" aria-hidden="true">
          {enabled ? `${formatTime(currentTime)} / ${formatTime(duration)}` : '--:-- / --:--'}
        </span>
        <div className="audio-volume">
          <button
            type="button"
            className="audio-icon-btn"
            onClick={toggleMute}
            disabled={!enabled}
            aria-label={muted ? 'Unmute' : 'Mute'}
            title={muted ? 'Unmute' : 'Mute'}
          >
            {muted ? (
              <VolumeX size={14} strokeWidth={2} />
            ) : (
              <Volume2 size={14} strokeWidth={2} />
            )}
          </button>
          <input
            type="range"
            className="audio-vol"
            min={0}
            max={1}
            step={0.05}
            value={muted ? 0 : volume}
            onChange={(e) => changeVolume(Number(e.target.value))}
            aria-label="Volume"
          />
        </div>
        <a
          className="audio-icon-btn audio-download"
          href={downloadUrl(src)}
          download
          aria-label={`Download ${label}`}
          title="Download audio"
        >
          <Download size={14} strokeWidth={2} />
        </a>
      </div>
      {failed && (
        <p className="audio-error muted" role="alert">
          Audio could not be loaded.
        </p>
      )}
    </div>
  )
}
