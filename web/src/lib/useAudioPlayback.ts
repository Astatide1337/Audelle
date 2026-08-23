import { useCallback, useEffect, useRef, useState } from 'react'
import { prepareAudio } from './api'

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
  const [wantsPlayback, setWantsPlayback] = useState(false)
  const [isPlaying, setIsPlaying] = useState(false)
  const [playbackTime, setPlaybackTime] = useState(0)
  const [duration, setDuration] = useState(0)
  const [errorFor, setErrorFor] = useState<string | null>(null)
  const [sourceFor, setSourceFor] = useState<string | null>(null)
  const [preparedFor, setPreparedFor] = useState<string | null>(null)

  useEffect(() => {
    onEndedRef.current = onEnded
  }, [onEnded])

  useEffect(() => {
    const audio = new Audio()
    audio.preload = 'auto'
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
      audio.pause()
      audio.removeAttribute('src')
      audio.load()
      audioRef.current = null
    }
  }, [])

  useEffect(() => {
    const audio = audioRef.current
    if (!audio || !videoId) return
    const continuePlayback = wantsPlayback
    audio.pause()
    setPlaybackTime(0)
    setDuration(0)
    setErrorFor(null)

    // Assign the same-origin URL before the user gesture. Safari can then
    // start its network-backed media request from the synchronous tap while
    // retaining user activation for play().
    audio.dataset.videoId = videoId
    audio.src = `/api/audio/${encodeURIComponent(videoId)}`
    audio.load()
    setSourceFor(videoId)

    // Start the expensive resolve/transcode while the result transition is
    // still covering the player. Once the finite MP3 exists, let the browser
    // preload its metadata/ranges as its own policy allows.
    let active = true
    void prepareAudio(videoId)
      .then(() => {
        if (!active || audio.dataset.videoId !== videoId) return
        setPreparedFor(videoId)
      })
      .catch(() => {
        if (active) setErrorFor(videoId)
      })

    // A user who was already listening has granted this media element
    // playback permission. Preserve that intent across src changes instead
    // of making Safari require a pause/play double tap after Next.
    if (continuePlayback) {
      void audio.play().catch(() => {
        if (active) setErrorFor(videoId)
      })
    }

    return () => {
      active = false
      audio.pause()
      audio.removeAttribute('src')
      audio.load()
    }
    // wantsPlayback is intentionally sampled only when the source changes;
    // including it would reload the current track on every Play/Pause tap.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [videoId])

  const play = useCallback(() => {
    const audio = audioRef.current
    if (!audio || !videoId) return
    setWantsPlayback(true)
    setErrorFor(null)
    if (audio.error) audio.load()
    void audio.play().catch(() => setErrorFor(videoId))
  }, [videoId])

  const pause = useCallback(() => {
    setWantsPlayback(false)
    audioRef.current?.pause()
  }, [])

  const togglePlay = useCallback(() => {
    const audio = audioRef.current
    if (!audio || !videoId) return
    if (audio.paused) {
      setWantsPlayback(true)
      setErrorFor(null)
      if (audio.error) audio.load()
      void audio.play().catch(() => setErrorFor(videoId))
    } else {
      setWantsPlayback(false)
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
    setWantsPlayback(true)
    setPlaybackTime(0)
    if (audio.error) audio.load()
    void audio.play().catch(() => setErrorFor(videoId))
  }, [videoId])

  const hasError = errorFor === 'player' || errorFor === videoId
  // Network readiness is reported by media events, not a preflight fetch/blob
  // load which can lose Safari's user-activation allowance.
  const isReady = sourceFor === videoId
  const isPrepared = preparedFor === videoId
  return { isReady, isPrepared, isPlaying, playbackTime, duration, hasError, play, pause, togglePlay, seek, restart }
}
