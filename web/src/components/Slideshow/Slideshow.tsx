import { useCallback, useEffect, useRef, useState } from 'react'
import gsap from 'gsap'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import type { Track } from '../../lib/types'
import { formatClock, formatPlays } from '../../lib/format'
import { DownloadCancelledError, downloadPlaylistZip, saveBlob, type DownloadResult } from '../../lib/download'
import { buildPlaylistShareUrl, copyTextToClipboard, playlistTitleFromPrompt } from '../../lib/share'
import { useAudioPlayback } from '../../lib/useAudioPlayback'
import { AudioVisualizer } from '../AudioVisualizer'
import { TrackInfoDialog } from '../TrackInfoDialog'
import { Button } from '../ui/Button'

/**
 * Ported from Filip Zrnzevic's "[gsap/slideshow] Vertical Zoom Slideshow N°3"
 * (https://codepen.io/filipz/pen/yyyBwXP). Same timeline structure — scale +
 * yPercent entrance, filter contrast/saturate pulse on the outgoing image,
 * a mid-timeline zoom-settle — ported from vanilla DOM/class logic into React
 * refs driving GSAP directly, since GSAP needs real DOM nodes either way.
 * Bottom UI layout (section label, counter, title, thumbnail filmstrip) and
 * CSS values (thumb size, spacing, background-position: left center) carried
 * over as closely as reasonably fits our track data instead of static images.
 */

interface SlideshowProps {
  tracks: Track[]
  playlistTitle: string
  playlistPrompt: string
  playlistSeed: number
  onClose: () => void
  onMusicReady?: () => void
}

type RepeatMode = 'off' | 'all' | 'one'

type DownloadState =
  | { stage: 'idle' }
  | {
      stage: 'running'
      currentIndex: number
      label: string
      receivedBytes: number
      totalBytes: number | null
      completedCount: number
      failedCount: number
    }
  | { stage: 'done'; savedCount: number; failed: { fileName: string; reason: string }[]; cancelled: boolean }

export function Slideshow({ tracks, playlistTitle, playlistPrompt, playlistSeed, onClose, onMusicReady }: SlideshowProps) {
  const slideRefs = useRef<(HTMLDivElement | null)[]>([])
  const innerRefs = useRef<(HTMLDivElement | null)[]>([])
  const filmstripRef = useRef<HTMLDivElement>(null)

  const currentRef = useRef(0)
  const isAnimatingRef = useRef(false)
  const pendingRef = useRef<number | null>(null)
  const [currentIndex, setCurrentIndex] = useState(0)
  const [repeatMode, setRepeatMode] = useState<RepeatMode>('off')
  const [downloadState, setDownloadState] = useState<DownloadState>({ stage: 'idle' })
  const [downloadToastVisible, setDownloadToastVisible] = useState(false)
  const [repeatToast, setRepeatToast] = useState<{ mode: RepeatMode; message: string } | null>(null)
  const [shareState, setShareState] = useState<'idle' | 'copied' | 'failed'>('idle')
  const [infoOpen, setInfoOpen] = useState(false)
  const downloadAbortRef = useRef<AbortController | null>(null)
  const prefersReducedMotion = useReducedMotion()

  const count = tracks.length
  const track = tracks[currentIndex]

  const animateTo = useCallback(
    (target: number) => {
      if (isAnimatingRef.current) {
        pendingRef.current = target
        return
      }
      if (target === currentRef.current) return

      const previous = currentRef.current
      const direction = target > previous ? 1 : -1
      isAnimatingRef.current = true
      currentRef.current = target
      setCurrentIndex(target)

      const currentSlide = slideRefs.current[previous]
      const currentInner = innerRefs.current[previous]
      const upcomingSlide = slideRefs.current[target]
      const upcomingInner = innerRefs.current[target]
      if (!currentSlide || !currentInner || !upcomingSlide || !upcomingInner) {
        isAnimatingRef.current = false
        return
      }

      if (prefersReducedMotion) {
        gsap.set(currentSlide, { autoAlpha: 0 })
        gsap.set(upcomingSlide, { autoAlpha: 1 })
        isAnimatingRef.current = false
        return
      }

      // The whole transition takes ~1.7s of timeline. If it never completes
      // (throttled rAF in a background tab, interrupted frame loop) the lock
      // below would wedge navigation permanently, so a watchdog converges to
      // the finished state instead.
      let finished = false
      const finishTransition = () => {
        if (finished) return
        finished = true
        window.clearTimeout(watchdog)
        gsap.set(currentSlide, { clearProps: 'transform,opacity,visibility,zIndex' })
        gsap.set(currentInner, { clearProps: 'filter' })
        gsap.set(upcomingSlide, { clearProps: 'zIndex' })
        isAnimatingRef.current = false
        if (pendingRef.current !== null) {
          const next = pendingRef.current
          pendingRef.current = null
          setTimeout(() => animateTo(next), 50)
        }
      }
      const watchdog = window.setTimeout(() => {
        if (!finished) gsap.set(upcomingSlide, { scale: 1, yPercent: 0, autoAlpha: 1 })
        finishTransition()
      }, 2600)

      gsap
        .timeline({
          onStart: () => {
            gsap.set(upcomingSlide, { autoAlpha: 1, zIndex: 99 })
          },
          onComplete: finishTransition,
        })
        .addLabel('start', 0)
        .fromTo(
          upcomingSlide,
          { autoAlpha: 1, scale: 0.1, yPercent: direction === 1 ? 100 : -100 },
          { duration: 0.7, ease: 'expo', scale: 0.4, yPercent: 0 },
          'start',
        )
        .fromTo(
          upcomingInner,
          { filter: 'contrast(100%) saturate(100%)', transformOrigin: '100% 50%', scaleY: 4 },
          { duration: 0.7, ease: 'expo', scaleY: 1 },
          'start',
        )
        .fromTo(
          currentInner,
          { filter: 'contrast(100%) saturate(100%)' },
          { duration: 0.7, ease: 'expo', filter: 'contrast(120%) saturate(140%)' },
          'start',
        )
        .addLabel('middle', 'start+=0.6')
        .to(upcomingSlide, { duration: 1, ease: 'power4.inOut', scale: 1 }, 'middle')
        .to(currentSlide, { duration: 1, ease: 'power4.inOut', scale: 0.98, autoAlpha: 0 }, 'middle')
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [prefersReducedMotion],
  )

  const goNext = useCallback(() => animateTo((currentRef.current + 1) % count), [animateTo, count])
  const goPrev = useCallback(() => animateTo((currentRef.current - 1 + count) % count), [animateTo, count])

  // The hook reports when a track ended; repeat policy lives here.
  const endedRef = useRef<() => void>(() => {})
  const {
    isReady,
    isPlaying,
    playbackTime,
    duration,
    hasError: hasAudioError,
    togglePlay,
    seek,
    restart,
  } = useAudioPlayback(track?.id ?? null, () => endedRef.current())

  const handleEnded = useCallback(() => {
    if (repeatMode === 'one') {
      restart()
      return
    }
    if (currentRef.current < count - 1) {
      animateTo(currentRef.current + 1)
      return
    }
    if (repeatMode === 'all') animateTo(0)
    // repeat off at the end of the queue: stay stopped
  }, [repeatMode, count, animateTo, restart])

  useEffect(() => {
    endedRef.current = handleEnded
  }, [handleEnded])

  useEffect(() => {
    if (isReady || hasAudioError) onMusicReady?.()
  }, [hasAudioError, isReady, onMusicReady])

  useEffect(() => () => downloadAbortRef.current?.abort(), [])

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'ArrowRight') goNext()
      else if (e.key === 'ArrowLeft') goPrev()
      else if (e.key === 'Escape' && !infoOpen) onClose()
    }
    function handleWheel(e: WheelEvent) {
      const target = e.target
      if (target instanceof Element && filmstripRef.current?.contains(target)) return
      if (isAnimatingRef.current) return
      if (e.deltaY > 0) goNext()
      else if (e.deltaY < 0) goPrev()
    }
    window.addEventListener('keydown', handleKey)
    window.addEventListener('wheel', handleWheel, { passive: true })
    return () => {
      window.removeEventListener('keydown', handleKey)
      window.removeEventListener('wheel', handleWheel)
    }
  }, [goNext, goPrev, onClose, infoOpen])

  useEffect(() => {
    const active = filmstripRef.current?.querySelector<HTMLElement>('[data-active="true"]')
    active?.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' })
  }, [currentIndex])

  // Restarting is its own button; Previous is pure queue navigation.
  const goPrevious = useCallback(() => goPrev(), [goPrev])

  function cycleRepeat() {
    const next = repeatMode === 'off' ? 'all' : repeatMode === 'all' ? 'one' : 'off'
    setRepeatMode(next)
    setRepeatToast({
      mode: next,
      message: next === 'all' ? 'Playlist will repeat' : next === 'one' ? 'Current track will repeat' : 'Repeat turned off',
    })
  }

  useEffect(() => {
    if (!repeatToast) return
    const timer = window.setTimeout(() => setRepeatToast(null), 2400)
    return () => window.clearTimeout(timer)
  }, [repeatToast])

  async function startDownload() {
    if (downloadState.stage === 'running') return
    const controller = new AbortController()
    downloadAbortRef.current = controller
    setDownloadToastVisible(true)

    setDownloadState({
      stage: 'running',
      currentIndex: 0,
      label: tracks[0].name,
      receivedBytes: 0,
      totalBytes: null,
      completedCount: 0,
      failedCount: 0,
    })

    let result: DownloadResult | null = null
    try {
      result = await downloadPlaylistZip(
        tracks,
        {
          onTrackStart: (index) =>
            setDownloadState((state) =>
              state.stage === 'running'
                ? { ...state, currentIndex: index, label: tracks[index].name, receivedBytes: 0, totalBytes: null }
                : state,
            ),
          onTrackProgress: (_index, receivedBytes, totalBytes) =>
            setDownloadState((state) => (state.stage === 'running' ? { ...state, receivedBytes, totalBytes } : state)),
          onTrackDone: () =>
            setDownloadState((state) => (state.stage === 'running' ? { ...state, completedCount: state.completedCount + 1 } : state)),
          onTrackFailed: () =>
            setDownloadState((state) => (state.stage === 'running' ? { ...state, failedCount: state.failedCount + 1 } : state)),
        },
        controller.signal,
      )
      saveBlob(result.blob, `${playlistTitleFromPrompt(playlistTitle).replace(/[\\/:*?"<>|]/g, '') || 'audelle-playlist'}.zip`)
      setDownloadState({
        stage: 'done',
        savedCount: result.succeeded.length,
        failed: result.failed,
        cancelled: controller.signal.aborted,
      })
    } catch (error) {
      if (error instanceof DownloadCancelledError || controller.signal.aborted) {
        setDownloadState({ stage: 'done', savedCount: result?.succeeded.length ?? 0, failed: [], cancelled: true })
      } else {
        setDownloadState({
          stage: 'done',
          savedCount: result?.succeeded.length ?? 0,
          failed: [{ fileName: '', reason: error instanceof Error ? error.message : 'Download failed.' }],
          cancelled: false,
        })
      }
    } finally {
      downloadAbortRef.current = null
    }
  }

  useEffect(() => {
    if (shareState === 'idle') return
    const timer = window.setTimeout(() => setShareState('idle'), 2000)
    return () => window.clearTimeout(timer)
  }, [shareState])

  async function sharePlaylist() {
    const url = await buildPlaylistShareUrl(playlistTitle, playlistPrompt, playlistSeed, tracks).catch(() => null)
    if (!url) {
      setShareState('failed')
      return
    }
    const copied = await copyTextToClipboard(url)
    setShareState(copied ? 'copied' : 'failed')
  }

  if (!track) return null

  const audioUnavailable = hasAudioError
  const seekValue = Math.min(playbackTime, duration > 0 ? duration : playbackTime)
  const progressPercent =
    downloadState.stage === 'running' && downloadState.totalBytes
      ? Math.min(100, Math.round((downloadState.receivedBytes / downloadState.totalBytes) * 100))
      : null

  return (
    <div className="fixed inset-0 z-10 overflow-hidden bg-canvas">
      <div className="group fixed left-6 top-6 z-20 sm:left-10 sm:top-8">
        <Button
          type="button"
          onClick={() => setInfoOpen(true)}
          aria-label="Track info"
          aria-describedby="track-info-tooltip"
          variant="surface"
          size="icon-sm"
          className="text-ink"
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
            <circle cx="12" cy="12" r="8" />
            <path d="M12 10.5v5M12 7.5h.01" strokeLinecap="round" />
          </svg>
        </Button>
        <span id="track-info-tooltip" role="tooltip" className="ui-tooltip pointer-events-none absolute left-0 top-11 w-max px-3 py-2 text-xs leading-5 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
          Track info
        </span>
      </div>

      {/* isolate: contains the transient zIndex:99 set during transitions to this
          stacking context, so the animating image can never render above the
          text/UI layer below (which sits in the parent's stacking context). */}
      <div className="absolute inset-0 z-0 isolate grid place-items-center">
        {tracks.map((t, i) => (
          <div
            key={t.id}
            ref={(el) => {
              slideRefs.current[i] = el
            }}
            className={`col-start-1 row-start-1 h-full w-full overflow-hidden ${
              i === 0 ? 'visible opacity-100' : 'invisible opacity-0'
            }`}
          >
            <div
              ref={(el) => {
                innerRefs.current[i] = el
              }}
              className="h-full w-full bg-contain bg-center bg-no-repeat sm:bg-cover sm:bg-left"
              style={t.album_art ? { backgroundImage: `url(${t.album_art})` } : { backgroundColor: 'var(--color-surface-raised)' }}
            />
          </div>
        ))}
      </div>

      <div className="pointer-events-none absolute inset-0 bg-gradient-to-t from-canvas via-canvas/40 to-transparent" />

      <Button
        type="button"
        onClick={onClose}
        variant="surface"
        size="sm"
        className="fixed right-6 top-6 z-20 sm:right-10 sm:top-8"
      >
        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-3.5 w-3.5">
          <circle cx="11" cy="11" r="6" />
          <path d="m16 16 4 4" strokeLinecap="round" />
        </svg>
        New vibe
      </Button>

      <div className="absolute inset-x-0 bottom-0 z-20 flex max-h-[92dvh] flex-col items-center gap-3 overflow-y-auto overscroll-contain px-6 pb-6 text-center sm:pb-8">
        <AnimatePresence mode="popLayout" initial={false}>
          <motion.h2
            key={track.id}
            initial={prefersReducedMotion ? false : { opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            exit={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, y: -16 }}
            transition={{ duration: prefersReducedMotion ? 0 : 0.4, ease: 'easeOut' }}
            className="type-display max-w-2xl text-4xl leading-[0.95] text-ink sm:text-6xl"
          >
            {track.name}
          </motion.h2>
        </AnimatePresence>
        <p className="label-meta text-ink-dim">
          {track.artists.join(', ')}
          {track.year > 0 && <span> — {track.year}</span>}
          {track.popularity > 0 && <span className="text-ember"> · {formatPlays(track.popularity)}</span>}
        </p>

        <AudioVisualizer isPlaying={isPlaying} playbackTime={playbackTime} trackId={track.id} />
        {hasAudioError && (
          <p className="max-w-sm text-xs text-ink-dim" role="status">
            Audio preview is unavailable, but you can still browse and download the playlist.
          </p>
        )}

        {/* Transport controls */}
        <div role="group" aria-label="Playback controls" className="playback-controls flex w-full max-w-xl flex-col items-center gap-2">
          <div className="flex items-center gap-2">
            <Button type="button" onClick={restart} disabled={audioUnavailable || !isReady} aria-label="Restart track" variant="surface" size="icon-sm" className="text-ink">
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                <path d="M3 12a9 9 0 1 0 2.64-6.36L3 8" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M3 3v5h5" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </Button>
            <Button type="button" onClick={goPrevious} aria-label="Previous track" variant="surface" size="icon-sm" className="text-ink">
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                <path d="M7 5v14" strokeLinecap="round" />
                <path d="M18 6.6v10.8a.5.5 0 0 1-.78.42l-7.44-5.4a.5.5 0 0 1 0-.84l7.44-5.4a.5.5 0 0 1 .78.42Z" fill="currentColor" stroke="none" />
              </svg>
            </Button>
            <Button type="button" onClick={togglePlay} disabled={audioUnavailable} aria-label={isPlaying ? 'Pause' : 'Play'} size="icon" className="text-canvas">
              {isPlaying ? (
                <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor">
                  <rect x="6.5" y="5" width="3.6" height="14" rx="1" />
                  <rect x="13.9" y="5" width="3.6" height="14" rx="1" />
                </svg>
              ) : (
                <svg aria-hidden="true" viewBox="0 0 24 24" className="h-5 w-5" fill="currentColor">
                  <path d="M8 5.5v13a.6.6 0 0 0 .92.5l10.2-6.5a.6.6 0 0 0 0-1L8.92 5a.6.6 0 0 0-.92.5Z" />
                </svg>
              )}
            </Button>
            <Button type="button" onClick={goNext} aria-label="Next track" variant="surface" size="icon-sm" className="text-ink">
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                <path d="M17 5v14" strokeLinecap="round" />
                <path d="M6 6.6v10.8a.5.5 0 0 0 .78.42l7.44-5.4a.5.5 0 0 0 0-.84L6.78 6.18A.5.5 0 0 0 6 6.6Z" fill="currentColor" stroke="none" />
              </svg>
            </Button>
            <Button
              type="button"
              onClick={cycleRepeat}
              aria-label={`Repeat: ${repeatMode === 'off' ? 'off' : repeatMode === 'all' ? 'entire playlist' : 'current track'}`}
              title={repeatMode === 'off' ? 'Repeat off' : repeatMode === 'all' ? 'Repeat playlist' : 'Repeat current track'}
              aria-pressed={repeatMode !== 'off'}
              variant="surface"
              size="icon-sm"
              className={`${repeatMode === 'off' ? 'text-ink-dim' : 'text-ember'} relative`}
            >
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                <path d="m17 2 4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M3 11v-1a4 4 0 0 1 4-4h14" strokeLinecap="round" strokeLinejoin="round" />
                <path d="m7 22-4-4 4-4" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M21 13v1a4 4 0 0 1-4 4H3" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              {repeatMode === 'one' && (
                <span aria-hidden="true" className="absolute -right-0.5 -bottom-0.5 rounded-full bg-ember px-[0.3rem] text-[0.55rem] font-bold leading-4 text-canvas">
                  1
                </span>
              )}
            </Button>
          </div>

          <div className="flex w-full items-center gap-3">
            <span className="label-meta w-10 shrink-0 text-right text-ink-dim tabular-nums">{formatClock(playbackTime)}</span>
            <input
              type="range"
              min={0}
              max={duration > 0 ? Math.floor(duration) : 0}
              step={1}
              value={Math.floor(seekValue)}
              onChange={(e) => seek(Number(e.target.value))}
              disabled={audioUnavailable || !isReady || duration <= 0}
              aria-label="Seek within track"
              className="ui-range min-w-0 flex-1"
              style={{ '--progress': `${duration > 0 ? (seekValue / duration) * 100 : 0}%` } as React.CSSProperties}
            />
            <span className="label-meta w-10 shrink-0 text-left text-ink-dim tabular-nums">{formatClock(duration)}</span>
          </div>
        </div>

        {/* Playlist actions */}
        <div className="flex flex-wrap items-center justify-center gap-2">
          {downloadState.stage === 'running' ? (
            <Button type="button" onClick={() => downloadAbortRef.current?.abort()} variant="outline" size="md">
              Cancel download
            </Button>
          ) : (
            <Button type="button" onClick={startDownload} size="md">
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                <path d="M12 3v12m0 0 4.5-4.5M12 15l-4.5-4.5" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M4 19h16" strokeLinecap="round" />
              </svg>
              Download playlist
            </Button>
          )}
          <Button type="button" onClick={sharePlaylist} variant="outline" size="md">
            {shareState === 'copied' ? 'Link copied ✓' : shareState === 'failed' ? 'Copy failed' : 'Share playlist'}
          </Button>
        </div>

        <div
          ref={filmstripRef}
          className="filmstrip-scrollbar mx-auto mt-1 flex h-20 w-[min(45rem,calc(100vw-3rem))] shrink-0 overflow-x-auto overflow-y-hidden"
          role="tablist"
          aria-orientation="horizontal"
          aria-label="Tracks"
        >
          {tracks.map((t, i) => (
            <button
              key={t.id}
              type="button"
              role="tab"
              aria-selected={i === currentIndex}
              tabIndex={i === currentIndex ? 0 : -1}
              aria-label={`${t.name} thumbnail`}
              data-active={i === currentIndex}
              onClick={() => animateTo(i)}
              className={`ui-filmstrip-tile h-20 w-[7.5rem] shrink-0 overflow-hidden rounded-none border-0 ${
                i === currentIndex ? 'ui-filmstrip-tile--active' : 'ui-filmstrip-tile--inactive'
              }`}
            >
              {t.album_art ? (
                <img src={t.album_art} alt="" className="h-full w-full object-cover" />
              ) : (
                <div className="h-full w-full bg-surface-raised" />
              )}
            </button>
          ))}
        </div>
      </div>

      <AnimatePresence>
        {downloadToastVisible && downloadState.stage !== 'idle' && (
          <motion.aside
            className="download-toast fixed right-4 top-20 z-40 w-[min(24rem,calc(100vw-2rem))] p-4 text-left sm:right-8 sm:top-24"
            role="region"
            aria-label="Download status"
            aria-live="polite"
            initial={prefersReducedMotion ? false : { opacity: 0, x: 18, scale: 0.97, filter: 'blur(8px)' }}
            animate={{ opacity: 1, x: 0, scale: 1, filter: 'blur(0px)' }}
            exit={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, x: 10, scale: 0.98, filter: 'blur(4px)' }}
            transition={prefersReducedMotion ? { duration: 0 } : { type: 'spring', stiffness: 430, damping: 34, mass: 0.75 }}
          >
            <div className="flex items-start gap-3">
              <div className="min-w-0 flex-1">
                <p className="label-meta text-ink">
                  {downloadState.stage === 'running'
                    ? `Downloading ${Math.min(downloadState.currentIndex + 1, tracks.length)} of ${tracks.length}`
                    : downloadState.cancelled
                      ? 'Download cancelled'
                      : downloadState.failed.length > 0
                        ? 'Download finished with issues'
                        : 'Playlist downloaded'}
                </p>
                {downloadState.stage === 'running' ? (
                  <p className="mt-1 truncate text-sm text-ink-dim">
                    {downloadState.label}
                    {downloadState.failedCount > 0 && <span> · {downloadState.failedCount} failed</span>}
                  </p>
                ) : downloadState.cancelled ? (
                  <p className="mt-1 text-sm text-ink-dim">No files were saved.</p>
                ) : downloadState.failed.length > 0 ? (
                  <p className="mt-1 text-sm text-ink-dim">Saved {downloadState.savedCount} of {tracks.length}. {downloadState.failed.length} could not be downloaded.</p>
                ) : (
                  <p className="mt-1 text-sm text-ink-dim">Saved all {downloadState.savedCount} tracks.</p>
                )}
              </div>
              <button
                type="button"
                onClick={() => setDownloadToastVisible(false)}
                aria-label="Dismiss download notification"
                className="grid h-9 w-9 shrink-0 place-items-center rounded-full text-ink-dim transition-colors hover:bg-surface-raised hover:text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ink"
              >
                <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                  <path d="m7 7 10 10M17 7 7 17" strokeLinecap="round" />
                </svg>
              </button>
            </div>
            {downloadState.stage === 'running' && (
              <div className="download-progress-track mt-3">
                <div className="download-progress-fill" style={{ width: `${progressPercent ?? 4}%` }} />
              </div>
            )}
          </motion.aside>
        )}
      </AnimatePresence>

      <div className="pointer-events-none fixed inset-x-4 bottom-6 z-50 flex justify-center sm:bottom-8">
        <AnimatePresence mode="wait">
          {repeatToast && (
            <motion.div
              key={repeatToast.mode}
              className="status-toast flex max-w-[calc(100vw-2rem)] items-center gap-2.5 px-4 py-3"
              role="status"
              aria-live="polite"
              initial={prefersReducedMotion ? false : { opacity: 0, y: 18, scale: 0.96, filter: 'blur(8px)' }}
              animate={{ opacity: 1, y: 0, scale: 1, filter: 'blur(0px)' }}
              exit={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, y: 8, scale: 0.98, filter: 'blur(4px)' }}
              transition={prefersReducedMotion ? { duration: 0 } : { type: 'spring', stiffness: 460, damping: 34, mass: 0.7 }}
            >
              <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4 shrink-0 text-ink-dim">
                <path d="m17 2 4 4-4 4" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M3 11v-1a4 4 0 0 1 4-4h14" strokeLinecap="round" strokeLinejoin="round" />
                <path d="m7 22-4-4 4-4" strokeLinecap="round" strokeLinejoin="round" />
                <path d="M21 13v1a4 4 0 0 1-4 4H3" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              <span className="text-sm font-medium text-ink">{repeatToast.message}</span>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      {infoOpen && <TrackInfoDialog track={track} prompt={playlistPrompt} onClose={() => setInfoOpen(false)} />}
    </div>
  )
}
