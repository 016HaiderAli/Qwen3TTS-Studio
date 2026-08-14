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

function PlayIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M8 5v14l11-7z" />
    </svg>
  )
}

function PauseIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M6 5h4v14H6zm8 0h4v14h-4z" />
    </svg>
  )
}

function VolumeIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3A4.5 4.5 0 0 0 14 7.97v8.05A4.5 4.5 0 0 0 16.5 12z" />
    </svg>
  )
}

function MutedIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51A8.919 8.919 0 0 0 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3 3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06a8.99 8.99 0 0 0 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4 9.91 6.09 12 8.18V4z" />
    </svg>
  )
}

function DownloadIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <path d="M5 20h14v-2H5v2zM19 9h-4V3H9v6H5l7 7 7-7z" />
    </svg>
  )
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
  const pct = enabled && duration && duration > 0 ? Math.min(100, (currentTime / duration) * 100) : 0

  return (
    <div className="audio-player" role="group" aria-label={`Audio player: ${label}`}>
      <audio ref={audioRef} src={src} preload="metadata" className="audio-source" />
      <div className="audio-player-main">
        <button
          type="button"
          className="audio-play"
          onClick={() => void togglePlay()}
          disabled={!enabled}
          aria-label={playing ? 'Pause' : 'Play'}
        >
          {playing ? <PauseIcon /> : <PlayIcon />}
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
          aria-valuetext={enabled ? `${formatTime(currentTime)} of ${formatTime(duration)}` : undefined}
        />
        <span className="audio-time" aria-hidden="true">
          {enabled ? `${formatTime(currentTime)} / ${formatTime(duration)}` : '--:-- / --:--'}
        </span>
        <div className="audio-volume">
          <button
            type="button"
            className="audio-mute"
            onClick={toggleMute}
            disabled={!enabled}
            aria-label={muted ? 'Unmute' : 'Mute'}
          >
            {muted ? <MutedIcon /> : <VolumeIcon />}
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
          className="audio-download"
          href={downloadUrl(src)}
          download
          aria-label={`Download ${label}`}
          title="Download audio"
        >
          <DownloadIcon />
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
