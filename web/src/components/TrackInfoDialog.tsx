import { useEffect, useId, useRef, useState } from 'react'
import { motion, useReducedMotion } from 'motion/react'
import type { Track } from '../lib/types'
import { formatPlays } from '../lib/format'
import { buildPlaylistShareUrl, copyTextToClipboard, playlistTitleFromPrompt } from '../lib/share'
import { Button } from './ui/Button'

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

interface TrackInfoDialogProps {
  track: Track
  prompt: string
  onClose: () => void
}

export function TrackInfoDialog({ track, prompt, onClose }: TrackInfoDialogProps) {
  const titleId = useId()
  const dialogRef = useRef<HTMLDivElement>(null)
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle')
  const prefersReducedMotion = useReducedMotion()

  useEffect(() => {
    const previousFocus = document.activeElement as HTMLElement | null
    dialogRef.current?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR)?.focus()
    const previousBodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.body.style.overflow = previousBodyOverflow
      previousFocus?.focus()
    }
  }, [])

  useEffect(() => {
    if (copyState === 'idle') return
    const timer = window.setTimeout(() => setCopyState('idle'), 2000)
    return () => window.clearTimeout(timer)
  }, [copyState])

  function handleKeyDown(event: React.KeyboardEvent) {
    if (event.key === 'Escape') {
      event.stopPropagation()
      onClose()
      return
    }
    if (event.key !== 'Tab') return

    const dialog = dialogRef.current
    if (!dialog) return
    const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
    if (focusable.length === 0) return
    const firstEl = focusable[0]
    const lastEl = focusable[focusable.length - 1]

    if (event.shiftKey && document.activeElement === firstEl) {
      event.preventDefault()
      lastEl.focus()
    } else if (!event.shiftKey && document.activeElement === lastEl) {
      event.preventDefault()
      firstEl.focus()
    }
  }

  async function copyTrackLink() {
    const url = await buildPlaylistShareUrl(playlistTitleFromPrompt(track.name), prompt, 0, [track]).catch(() => null)
    const copied = url ? await copyTextToClipboard(url) : false
    setCopyState(copied ? 'copied' : 'failed')
  }

  return (
    <>
      <motion.div
        key="overlay"
        aria-hidden="true"
        onClick={onClose}
        className="ui-overlay fixed inset-0 z-40"
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        transition={{ duration: prefersReducedMotion ? 0 : 0.2 }}
      />
      <motion.div
        ref={dialogRef}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={handleKeyDown}
        className="ui-dialog fixed inset-x-0 bottom-0 z-40 max-h-[88dvh] overflow-y-auto border-t border-line bg-canvas p-6 sm:inset-0 sm:m-auto sm:h-fit sm:w-[26rem] sm:border"
        initial={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, y: 24 }}
        animate={{ opacity: 1, y: 0 }}
        exit={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, y: 24 }}
        transition={{ duration: prefersReducedMotion ? 0 : 0.25, ease: 'easeOut' }}
      >
        <div className="mb-5 flex items-start justify-between gap-3">
          <h2 id={titleId} className="label-meta text-ink-dim">
            Track info
          </h2>
          <Button
            type="button"
            onClick={onClose}
            aria-label="Close track info"
            variant="surface"
            size="icon-sm"
            className="text-ink-dim hover:text-ember"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
              <path d="m7 7 10 10M17 7 7 17" strokeLinecap="round" />
            </svg>
          </Button>
        </div>

        <div className="flex items-center gap-4">
          {track.album_art ? (
            <img src={track.album_art} alt="" width={96} height={96} className="h-24 w-24 shrink-0 rounded-lg object-cover" />
          ) : (
            <div className="h-24 w-24 shrink-0 rounded-lg bg-surface-raised" />
          )}
          <div className="min-w-0">
            <p className="type-body truncate text-lg font-semibold text-ink">{track.name}</p>
            <p className="label-meta mt-1 text-ink-dim">
              {track.artists.join(', ')}
              {track.year > 0 && <span> — {track.year}</span>}
            </p>
            {track.popularity > 0 && (
              <p className="label-meta mt-1 text-ember">{formatPlays(track.popularity)}</p>
            )}
          </div>
        </div>

        {prompt && (
          <div className="mt-5 border-t border-line pt-4">
            <p className="label-meta mb-1 text-ink-dim">Original prompt</p>
            <p className="type-body text-sm leading-6 text-ink">{prompt}</p>
          </div>
        )}

        <div className="mt-5 flex flex-col gap-2 border-t border-line pt-4">
          <a
            href={`https://music.youtube.com/watch?v=${track.id}`}
            target="_blank"
            rel="noreferrer"
            className={TRACK_ACTION_CLASS}
          >
            Open in YouTube Music ↗
          </a>
          <button type="button" onClick={copyTrackLink} className={TRACK_ACTION_CLASS}>
            {copyLabel(copyState)}
          </button>
        </div>
      </motion.div>
    </>
  )
}

function copyLabel(state: 'idle' | 'copied' | 'failed'): string {
  if (state === 'copied') return 'Link copied ✓'
  if (state === 'failed') return 'Copy failed — try again'
  return 'Copy track link'
}

const TRACK_ACTION_CLASS =
  'label-meta flex min-h-11 items-center justify-center rounded-full border border-line px-4 text-ink transition-colors hover:border-ember hover:text-ember focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ember'
