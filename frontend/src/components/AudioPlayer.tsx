export function AudioPlayer({ src, title }: { src: string; title?: string }) {
  return (
    <div className="audio-player">
      <audio controls preload="metadata" src={src} aria-label={title ?? 'audio'}>
        Your browser does not support audio playback.
      </audio>
    </div>
  )
}
