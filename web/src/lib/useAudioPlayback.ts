import { useCallback, useEffect, useRef, useState } from 'react'

/**
 * Native, same-origin MP3 playback.
 *
 * iPhone Safari requires media playback to begin from the user's activation.
 * Calling HTMLMediaElement.play() directly from the transport button preserves
 * that contract; an invisible third-party video iframe cannot do so reliably.
 */
export function useAudioPlayback(videoId: string | null, onEnded: () => void) {
  const audioRef = useRef<HTMLAudioElement | null>(null)
  const onEndedRef = useRef(onEnded)
  const shouldContinueRef = useRef(false)
  const [isPlaying, setIsPlaying] = useState(false)
  const [playbackTime, setPlaybackTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [errorFor, setErrorFor] = useState<string | null>(null)

  useEffect(() => {
    onEndedRef.current = onEnded
  }, [onEnded])

  useEffect(() => {
    const audio = new Audio()
    audio.preload = 'none'
    audio.addEventListener('playing', () => {
      setIsPlaying(true)
      setErrorFor(null)
    })
    audio.addEventListener('pause', () => setIsPlaying(false))
    audio.addEventListener('timeupdate', () => setPlaybackTime(audio.currentTime))
    audio.addEventListener('durationchange', () => {
      if (Number.isFinite(audio.duration)) setDuration(audio.duration)
    })
    audio.addEventListener('ended', () => {
      setIsPlaying(false)
      setPlaybackTime(0)
      onEndedRef.current()
    })
    audio.addEventListener('error', () => {
      setIsPlaying(false)
      setErrorFor(audio.dataset.videoId ?? 'player')
    })
    audioRef.current = audio

    return () => {
      shouldContinueRef.current = false
      audio.pause()
      audio.removeAttribute('src')
      audio.load()
      audioRef.current = null
    }
  }, [])

  useEffect(() => {
    const audio = audioRef.current
    if (!audio || !videoId) return
    const continuePlaying = shouldContinueRef.current
    audio.dataset.videoId = videoId
    audio.src = `/api/audio/${encodeURIComponent(videoId)}`
    audio.load()
    setPlaybackTime(0)
    setDuration(0)
    if (continuePlaying) {
      void audio.play().catch(() => setErrorFor(videoId))
    }
  }, [videoId])

  const play = useCallback(() => {
    const audio = audioRef.current
    if (!audio || !videoId) return
    shouldContinueRef.current = true
    setErrorFor(null)
    void audio.play().catch(() => setErrorFor(videoId))
  }, [videoId])

  const pause = useCallback(() => {
    shouldContinueRef.current = false
    audioRef.current?.pause()
  }, [])

  const togglePlay = useCallback(() => {
    const audio = audioRef.current
    if (!audio || !videoId) return
    if (audio.paused) {
      shouldContinueRef.current = true
      setErrorFor(null)
      void audio.play().catch(() => setErrorFor(videoId))
    } else {
      shouldContinueRef.current = false
      audio.pause()
    }
  }, [videoId])

  const seek = useCallback((seconds: number) => {
    const audio = audioRef.current
    if (!audio) return
    const clamped = Math.max(0, Math.min(seconds, Number.isFinite(audio.duration) ? audio.duration : seconds))
    audio.currentTime = clamped
    setPlaybackTime(clamped)
  }, [])

  const restart = useCallback(() => {
    const audio = audioRef.current
    if (!audio || !videoId) return
    audio.currentTime = 0
    shouldContinueRef.current = true
    setPlaybackTime(0)
    void audio.play().catch(() => setErrorFor(videoId))
  }, [videoId])

  const hasError = errorFor === 'player' || errorFor === videoId
  const isReady = true
  return { isReady, isPlaying, playbackTime, duration, hasError, play, pause, togglePlay, seek, restart }
}
