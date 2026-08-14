import { afterEach, describe, expect, it, vi } from 'vitest'
import { act, fireEvent, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { AudioPlayer } from './AudioPlayer'

function getAudio(container: HTMLElement): HTMLAudioElement {
  const audio = container.querySelector('audio')
  if (!audio) throw new Error('no <audio> element rendered')
  return audio
}

function loadMetadata(container: HTMLElement, duration: number) {
  act(() => {
    const audio = getAudio(container)
    Object.defineProperty(audio, 'duration', { value: duration, configurable: true })
    Object.defineProperty(audio, 'currentTime', { writable: true, value: 0, configurable: true })
    audio.dispatchEvent(new Event('loadedmetadata'))
  })
}

describe('AudioPlayer', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('starts disabled before audio metadata is available', () => {
    render(<AudioPlayer src="/api/audio.wav" title="Sample" />)
    expect(screen.getByRole('button', { name: 'Play' })).toBeDisabled()
    expect(screen.getByRole('slider', { name: 'Seek' })).toBeDisabled()
    expect(screen.getByText('--:-- / --:--')).toBeInTheDocument()
  })

  it('enables controls and shows duration after metadata loads', () => {
    const { container } = render(<AudioPlayer src="/api/audio.wav" title="Sample" />)
    loadMetadata(container, 65)
    expect(screen.getByRole('button', { name: 'Play' })).not.toBeDisabled()
    expect(screen.getByRole('slider', { name: 'Seek' })).not.toBeDisabled()
    expect(screen.getByText('0:00 / 1:05')).toBeInTheDocument()
  })

  it('plays and pauses the underlying audio element', async () => {
    const user = userEvent.setup()
    const { container } = render(<AudioPlayer src="/api/audio.wav" title="Voice preview" />)
    loadMetadata(container, 10)
    const audio = getAudio(container)
    const play = vi.spyOn(audio, 'play').mockResolvedValue(undefined)
    const pause = vi.spyOn(audio, 'pause').mockImplementation(() => {})

    await user.click(screen.getByRole('button', { name: 'Play' }))
    expect(play).toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Pause' })).toBeInTheDocument()

    Object.defineProperty(audio, 'paused', { get: () => false, configurable: true })
    await user.click(screen.getByRole('button', { name: 'Pause' }))
    expect(pause).toHaveBeenCalled()
    expect(screen.getByRole('button', { name: 'Play' })).toBeInTheDocument()
  })

  it('updates the elapsed time as the audio plays', () => {
    const { container } = render(<AudioPlayer src="/api/audio.wav" title="Sample" />)
    loadMetadata(container, 100)
    act(() => {
      Object.defineProperty(getAudio(container), 'currentTime', {
        writable: true,
        value: 42,
        configurable: true,
      })
      getAudio(container).dispatchEvent(new Event('timeupdate'))
    })
    expect(screen.getByText('0:42 / 1:40')).toBeInTheDocument()
  })

  it('seeks by writing to the underlying audio currentTime', () => {
    const { container } = render(<AudioPlayer src="/api/audio.wav" title="Sample" />)
    loadMetadata(container, 100)
    const seek = screen.getByRole('slider', { name: 'Seek' }) as HTMLInputElement
    fireEvent.change(seek, { target: { value: '42' } })
    expect(getAudio(container).currentTime).toBe(42)
    expect(screen.getByText('0:42 / 1:40')).toBeInTheDocument()
  })

  it('adjusts volume and unmutes from the volume control', () => {
    const { container } = render(<AudioPlayer src="/api/audio.wav" title="Sample" />)
    const audio = getAudio(container)
    Object.defineProperty(audio, 'volume', { writable: true, value: 1, configurable: true })
    Object.defineProperty(audio, 'muted', { writable: true, value: false, configurable: true })
    loadMetadata(container, 10)

    const vol = screen.getByRole('slider', { name: 'Volume' }) as HTMLInputElement
    fireEvent.change(vol, { target: { value: '0.5' } })
    expect(audio.volume).toBe(0.5)
    expect(audio.muted).toBe(false)

    fireEvent.click(screen.getByRole('button', { name: 'Mute' }))
    expect(audio.muted).toBe(true)
    expect(screen.getByRole('button', { name: 'Unmute' })).toBeInTheDocument()
  })

  it('links the download button to the backend download URL', () => {
    render(<AudioPlayer src="/api/files/narrations/abc/audio" title="My narration" />)
    const link = screen.getByRole('link', { name: 'Download My narration' })
    expect(link).toHaveAttribute('href', '/api/files/narrations/abc/audio?download=true')
    expect(link).toHaveAttribute('download')
  })

  it('shows an error and disables playback when audio fails to load', () => {
    const { container } = render(<AudioPlayer src="/api/audio.wav" title="Sample" />)
    act(() => {
      getAudio(container).dispatchEvent(new Event('error'))
    })
    expect(screen.getByText('Audio could not be loaded.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Play' })).toBeDisabled()
  })

  it('resets to the loading state when the source changes', () => {
    const { container, rerender } = render(<AudioPlayer src="/api/a.wav" title="Sample" />)
    loadMetadata(container, 30)
    expect(screen.getByRole('button', { name: 'Play' })).not.toBeDisabled()

    rerender(<AudioPlayer src="/api/b.wav" title="Sample" />)
    expect(screen.getByRole('button', { name: 'Play' })).toBeDisabled()
    expect(screen.getByText('--:-- / --:--')).toBeInTheDocument()
  })
})
