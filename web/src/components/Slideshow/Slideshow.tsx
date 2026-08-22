import { useCallback, useEffect, useRef, useState } from 'react'
import gsap from 'gsap'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import type { Track } from '../../lib/types'
import { formatPlays } from '../../lib/format'
import { useYouTubeAudio } from '../../lib/useYouTubeAudio'
import { AudioVisualizer } from '../AudioVisualizer'
import { Button } from '../ui/Button'
import { buttonClassNames } from '../ui/buttonClassNames'
import { createYouTubeMusicPlaylist, ExportAccessDeniedError, playlistNameFromPrompt, pollYouTubeMusicExport, startYouTubeMusicExport } from '../../lib/export'

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
  playlistPrompt: string
  onClose: () => void
  onMusicReady?: () => void
}

type ExportState =
  | { stage: 'idle' }
  | { stage: 'authorizing'; sessionId: string; userCode: string; verificationUrl: string; interval: number }
  | { stage: 'complete'; url: string }
  | { stage: 'blocked' }
  | { stage: 'error' }

export function Slideshow({ tracks, playlistPrompt, onClose, onMusicReady }: SlideshowProps) {
  const slideRefs = useRef<(HTMLDivElement | null)[]>([])
  const innerRefs = useRef<(HTMLDivElement | null)[]>([])
  const filmstripRef = useRef<HTMLDivElement>(null)

  const currentRef = useRef(0)
  const isAnimatingRef = useRef(false)
  const pendingRef = useRef<number | null>(null)
  const [currentIndex, setCurrentIndex] = useState(0)
  const [exportState, setExportState] = useState<ExportState>({ stage: 'idle' })
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

      gsap
        .timeline({
          onStart: () => {
            gsap.set(upcomingSlide, { autoAlpha: 1, zIndex: 99 })
          },
          onComplete: () => {
            gsap.set(currentSlide, { clearProps: 'transform,opacity,visibility,zIndex' })
            gsap.set(currentInner, { clearProps: 'filter' })
            gsap.set(upcomingSlide, { clearProps: 'zIndex' })
            isAnimatingRef.current = false
            if (pendingRef.current !== null) {
              const next = pendingRef.current
              pendingRef.current = null
              setTimeout(() => animateTo(next), 50)
            }
          },
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
  const { containerRef: audioContainerRef, isReady, isPlaying, playbackTime, hasError: hasAudioError } = useYouTubeAudio(track?.id ?? null, goNext)

  useEffect(() => {
    if (isReady || hasAudioError) onMusicReady?.()
  }, [hasAudioError, isReady, onMusicReady])

  const startExport = async () => {
    try {
      const start = await startYouTubeMusicExport()
      setExportState({
        stage: 'authorizing',
        sessionId: start.session_id,
        userCode: start.user_code,
        verificationUrl: start.verification_url,
        interval: start.interval,
      })
      window.open(start.verification_url, '_blank', 'noopener,noreferrer')
    } catch (error) {
      setExportState({ stage: error instanceof ExportAccessDeniedError ? 'blocked' : 'error' })
    }
  }

  useEffect(() => {
    if (exportState.stage !== 'authorizing') return
    let cancelled = false
    let timer: number | undefined
    const intervalMs = Math.max(exportState.interval, 2) * 1000

    const schedulePoll = () => {
      if (!cancelled) timer = window.setTimeout(poll, intervalMs)
    }

    const poll = async () => {
      try {
        const result = await pollYouTubeMusicExport(exportState.sessionId)
        if (cancelled) return
        if (result.status !== 'complete' || !result.authorized_session_id) {
          schedulePoll()
          return
        }

        // A device session is single-use. Stop scheduling before the slower
        // playlist write so a second poll cannot turn a successful export into
        // a misleading "could not be completed" state.
        if (timer !== undefined) window.clearTimeout(timer)
        const playlist = await createYouTubeMusicPlaylist(
          result.authorized_session_id,
          playlistNameFromPrompt(playlistPrompt),
          tracks.map((item) => item.id),
        )
        if (!cancelled) setExportState({ stage: 'complete', url: playlist.external_url })
      } catch (error) {
        if (!cancelled) setExportState({ stage: error instanceof ExportAccessDeniedError ? 'blocked' : 'error' })
      }
    }

    schedulePoll()
    return () => {
      cancelled = true
      if (timer !== undefined) window.clearTimeout(timer)
    }
  }, [exportState, playlistPrompt, tracks])

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'ArrowRight') goNext()
      else if (e.key === 'ArrowLeft') goPrev()
      else if (e.key === 'Escape') onClose()
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
  }, [goNext, goPrev, onClose])

  useEffect(() => {
    const active = filmstripRef.current?.querySelector<HTMLElement>('[data-active="true"]')
    active?.scrollIntoView({ behavior: 'smooth', inline: 'center', block: 'nearest' })
  }, [currentIndex])

  if (!track) return null

  return (
    <div className="fixed inset-0 z-10 overflow-hidden bg-canvas">
      <div className="group fixed left-6 top-6 z-20 sm:left-10 sm:top-8">
        <Button
          type="button"
          aria-label="How to browse tracks"
          aria-describedby="slideshow-help"
          variant="surface"
          size="icon-sm"
          className="text-ink"
        >
          <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
            <circle cx="12" cy="12" r="8" />
            <path d="M12 10.5v5M12 7.5h.01" strokeLinecap="round" />
          </svg>
        </Button>
        <span id="slideshow-help" role="tooltip" className="ui-tooltip pointer-events-none absolute left-0 top-11 w-52 px-3 py-2 text-xs leading-5 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
          Use the arrow keys or scroll to browse tracks.
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
              className="h-full w-full bg-cover bg-left bg-no-repeat"
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
        New search
      </Button>

      <div ref={audioContainerRef} className="pointer-events-none absolute h-px w-px overflow-hidden opacity-0" />

      <div className="absolute inset-x-0 bottom-0 z-20 flex max-h-[85vh] flex-col items-center gap-4 overflow-y-auto overscroll-contain px-6 pb-8 text-center sm:pb-10">
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
            Audio preview is unavailable, but you can still browse the playlist.
          </p>
        )}

        {exportState.stage === 'complete' ? (
          <a
            href={exportState.url}
            target="_blank"
            rel="noreferrer"
            className={buttonClassNames({ variant: 'primary', size: 'md' })}
          >
            Open exported playlist
          </a>
        ) : (
          <Button type="button" onClick={startExport} disabled={exportState.stage === 'authorizing'} size="md">
            {exportState.stage === 'authorizing' ? 'Connecting YouTube Music…' : 'Export playlist'}
          </Button>
        )}

        {exportState.stage === 'authorizing' && (
          <div className="ui-surface px-4 py-3 text-sm text-ink-dim backdrop-blur">
            <p>Enter this code in YouTube Music: <strong className="ml-1 text-ink">{exportState.userCode}</strong></p>
            <a href={exportState.verificationUrl} target="_blank" rel="noreferrer" className="ui-link label-meta mt-2 inline-block">Open YouTube Music ↗</a>
          </div>
        )}
        {exportState.stage === 'blocked' && (
          <div role="alert" className="max-w-sm text-sm text-ember">
            <p>Google blocked this account. Add the Google account you are using as an OAuth test user, then try again.</p>
            <a
              href="https://console.cloud.google.com/apis/credentials/consent"
              target="_blank"
              rel="noreferrer"
              className="ui-link label-meta mt-2 inline-block"
            >
              Open Google OAuth settings ↗
            </a>
          </div>
        )}
        {exportState.stage === 'error' && <p role="alert" className="text-sm text-ember">Export could not be completed. Try again.</p>}

        <div
          ref={filmstripRef}
          className="filmstrip-scrollbar mx-auto mt-2 flex h-20 w-[min(45rem,calc(100vw-3rem))] shrink-0 overflow-x-auto overflow-y-hidden"
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
    </div>
  )
}
