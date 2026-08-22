import { useEffect, useRef, useState } from 'react'

// Minimal surface of the YouTube IFrame Player API we actually use.
interface YTPlayer {
  loadVideoById: (videoId: string) => void
  getCurrentTime?: () => number
  destroy: () => void
}

interface YTStateChangeEvent {
  data: number
}

declare global {
  interface Window {
    YT?: {
      Player: new (
        element: HTMLElement,
        options: {
          height: string
          width: string
          playerVars: Record<string, number | string>
          events: { onReady: () => void; onStateChange: (event: YTStateChangeEvent) => void }
        },
      ) => YTPlayer
    }
    onYouTubeIframeAPIReady?: () => void
  }
}

let apiLoadPromise: Promise<void> | null = null
const YOUTUBE_API_TIMEOUT_MS = 10_000

function loadYouTubeApi(): Promise<void> {
  if (apiLoadPromise) return apiLoadPromise
  apiLoadPromise = new Promise((resolve, reject) => {
    let settled = false
    const timeout = window.setTimeout(() => {
      if (settled) return
      settled = true
      reject(new Error('YouTube player timed out'))
    }, YOUTUBE_API_TIMEOUT_MS)
    const finish = (callback: () => void) => {
      if (settled) return
      settled = true
      window.clearTimeout(timeout)
      callback()
    }
    if (window.YT?.Player) {
      finish(resolve)
      return
    }
    const previousReady = window.onYouTubeIframeAPIReady
    window.onYouTubeIframeAPIReady = () => {
      previousReady?.()
      finish(resolve)
    }
    const script = document.createElement('script')
    script.id = 'youtube-iframe-api'
    script.src = 'https://www.youtube.com/iframe_api'
    script.async = true
    script.onerror = () => finish(() => reject(new Error('YouTube player failed to load')))
    document.head.appendChild(script)
  })
  return apiLoadPromise
}

/**
 * Plays audio for the given YouTube video id via the official IFrame Player
 * API (embedding is sanctioned use, unlike extracting a raw stream URL).
 * Swapping videoId calls loadVideoById, which loads and starts playing the
 * new track — matches "play on focus, change on next" directly.
 */
export function useYouTubeAudio(videoId: string | null, onEnded: () => void) {
  const playerRef = useRef<YTPlayer | null>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const onEndedRef = useRef(onEnded)
  const pendingTrackResetRef = useRef(false)
  const [isReady, setIsReady] = useState(false)
  const [isPlaying, setIsPlaying] = useState(false)
  const [playbackTime, setPlaybackTime] = useState(0)
  const [hasError, setHasError] = useState(false)

  useEffect(() => {
    onEndedRef.current = onEnded
  }, [onEnded])

  useEffect(() => {
    let cancelled = false
    loadYouTubeApi().then(() => {
      if (cancelled) return
      if (!containerRef.current || !window.YT) {
        setHasError(true)
        return
      }
      try {
        playerRef.current = new window.YT.Player(containerRef.current, {
          height: '0',
          width: '0',
          playerVars: { controls: 0, disablekb: 1, playsinline: 1, origin: window.location.origin },
          events: {
            onReady: () => {
              if (!cancelled) setIsReady(true)
            },
            onStateChange: (event) => {
              if (cancelled) return
              // Treat the first playing state as a second readiness signal. In
              // some browsers the IFrame API emits the state event before the
              // onReady callback reaches the React effect.
              if (event.data === 1) setIsReady(true)
              setIsPlaying(event.data === 1)
              if (pendingTrackResetRef.current && (event.data === 1 || event.data === 3 || event.data === 5)) {
                pendingTrackResetRef.current = false
                setPlaybackTime(0)
              }
              if (event.data === 0) {
                setPlaybackTime(0)
                onEndedRef.current()
              }
            },
          },
        })
      } catch {
        setHasError(true)
      }
    }).catch(() => {
      if (!cancelled) setHasError(true)
    })
    return () => {
      cancelled = true
      playerRef.current?.destroy()
    }
  }, [])

  useEffect(() => {
    if (!isReady || !videoId) return
    pendingTrackResetRef.current = true
    playerRef.current?.loadVideoById(videoId)
  }, [isReady, videoId])

  useEffect(() => {
    if (!isPlaying) return

    let timer: number | undefined
    const pollPlayback = () => {
      const player = playerRef.current
      const nextTime = player?.getCurrentTime?.()
      if (typeof nextTime === 'number' && Number.isFinite(nextTime)) setPlaybackTime(nextTime)
      timer = window.setTimeout(pollPlayback, 100)
    }

    pollPlayback()
    return () => {
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [isPlaying])

  return { containerRef, isReady, isPlaying, playbackTime, hasError }
}
