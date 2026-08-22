import { useCallback, useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import { CatalogUnavailableError, generatePlaylist } from './lib/api'
import type { Filters, PlaylistResponse, Track } from './lib/types'
import { decodePlaylistSnapshot, type PlaylistSnapshot, type ShareTrack } from './lib/share'
import { FiltersPanel } from './components/FiltersPanel'
import { Slideshow } from './components/Slideshow/Slideshow'
import { TextEffect } from './components/core/text-effect'
import { ResultTransition } from './components/ResultTransition'
import { Button } from './components/ui/Button'

type Status = 'idle' | 'loading' | 'error' | 'done'

/** A playlist opened from a #v= share link — no server state involved. */
type SharedView =
  | { stage: 'idle' }
  | { stage: 'loading' }
  | { stage: 'invalid' }
  | { stage: 'ready'; snapshot: PlaylistSnapshot; tracks: Track[] }

function trackFromSnapshot(shareTrack: ShareTrack): Track {
  return {
    id: shareTrack.id,
    name: shareTrack.name,
    artists: shareTrack.artists,
    year: shareTrack.year,
    popularity: 0,
    watch_url: `https://www.youtube.com/watch?v=${shareTrack.id}`,
    album_art: shareTrack.albumArt ?? null,
  }
}

const EXAMPLE_PROMPTS = [
  'a late-night drive through the city',
  'a late-night vibe coding',
  'a rainy Sunday with nowhere to be',
  'a focused study session before finals',
]

function App() {
  const [text, setText] = useState('')
  const [filters, setFilters] = useState<Filters>({ genres: [] })
  const [status, setStatus] = useState<Status>('idle')
  const [result, setResult] = useState<PlaylistResponse | null>(null)
  const [errorMessage, setErrorMessage] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [isTyping, setIsTyping] = useState(false)
  const [typingPrompt, setTypingPrompt] = useState<string | null>(null)
  const [showSlideshow, setShowSlideshow] = useState(false)
  const [isTransitioningToResults, setIsTransitioningToResults] = useState(false)
  const [isMusicReady, setIsMusicReady] = useState(false)
  const [shared, setShared] = useState<SharedView>({ stage: 'idle' })
  const prefersReducedMotion = useReducedMotion()
  const hasInvalidYearRange =
    filters.yearFrom !== undefined && filters.yearTo !== undefined && filters.yearFrom > filters.yearTo
  const revealSlideshow = useCallback(() => setShowSlideshow(true), [])
  const finishResultTransition = useCallback(() => setIsTransitioningToResults(false), [])
  const completeResultTransition = useCallback(() => {
    finishResultTransition()
    setStatus('done')
  }, [finishResultTransition])
  const markMusicReady = useCallback(() => setIsMusicReady(true), [])

  // Share links live entirely in the URL fragment; decode locally on load
  // and whenever the hash changes (reshare, back/forward).
  useEffect(() => {
    let cancelled = false

    function loadFromHash() {
      const hash = window.location.hash
      if (!hash.startsWith('#v=')) {
        if (!cancelled) setShared({ stage: 'idle' })
        return
      }
      if (!cancelled) setShared({ stage: 'loading' })
      decodePlaylistSnapshot(hash.slice(3)).then((snapshot) => {
        if (cancelled) return
        if (!snapshot) {
          setShared({ stage: 'invalid' })
          return
        }
        setShared({ stage: 'ready', snapshot, tracks: snapshot.tracks.map(trackFromSnapshot) })
      })
    }

    loadFromHash()
    window.addEventListener('hashchange', loadFromHash)
    return () => {
      cancelled = true
      window.removeEventListener('hashchange', loadFromHash)
    }
  }, [])

  function closeSharedPlaylist() {
    history.replaceState(null, '', location.pathname + location.search)
    setShared({ stage: 'idle' })
  }

  function typePrompt(prompt: string) {
    if (isTyping || status === 'loading') return

    setStatus('idle')
    setErrorMessage('')
    setText('')
    setIsTyping(true)
    setTypingPrompt(prompt)

    if (prefersReducedMotion) {
      finishPrompt(prompt)
    }
  }

  function finishPrompt(prompt: string) {
    setText(prompt)
    setTypingPrompt(null)
    setIsTyping(false)
    requestAnimationFrame(() => textareaRef.current?.focus())
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!text.trim() || status === 'loading') return
    if (hasInvalidYearRange) {
      setErrorMessage('Choose an end year that is the same as or later than the start year.')
      setStatus('error')
      return
    }

    setResult(null)
    setIsMusicReady(false)
    setIsTransitioningToResults(true)
    setShowSlideshow(false)
    setStatus('loading')

    try {
      const response = await generatePlaylist(text.trim(), filters)
      setResult(response)
      if (response.tracks.length === 0) {
        setIsTransitioningToResults(false)
        setStatus('done')
      }
    } catch (err) {
      setIsTransitioningToResults(false)
      setErrorMessage(
        err instanceof CatalogUnavailableError
          ? "The catalog is briefly unavailable — give it a moment and try again."
          : "Something went wrong on this end. Try again.",
      )
      setStatus('error')
    }
  }

  // Mount the player as soon as data arrives, underneath the transition cover,
  // so the reveal can wait for the player to initialize.
  const shouldRenderSlideshow = Boolean(result?.tracks.length) && (showSlideshow || isTransitioningToResults)

  return (
    <div className="relative min-h-[100dvh] overflow-hidden bg-canvas">
      <div aria-hidden="true" className="ambient-glow pointer-events-none absolute inset-0">
        <div className="ambient-glow__ember" />
        <div className="ambient-glow__shade" />
      </div>

      {shared.stage === 'ready' ? (
        <Slideshow
          tracks={shared.tracks}
          playlistTitle={shared.snapshot.title}
          playlistPrompt={shared.snapshot.prompt}
          playlistSeed={shared.snapshot.seed}
          onClose={closeSharedPlaylist}
        />
      ) : shared.stage === 'loading' ? (
        <main className="relative mx-auto flex min-h-[100dvh] max-w-4xl items-center justify-center px-6">
          <p className="label-meta animate-pulse text-ink-dim">Opening shared playlist…</p>
        </main>
      ) : shared.stage === 'invalid' ? (
        <main className="relative mx-auto flex min-h-[100dvh] max-w-4xl flex-col items-center justify-center px-6 text-center">
          <img
            src="/audelle-mark.png"
            alt=""
            aria-hidden="true"
            width={36}
            height={40}
            decoding="async"
            className="h-10 w-auto object-contain"
          />
          <h1 className="type-display mt-4 text-3xl text-ink sm:text-4xl">This link didn't survive the trip</h1>
          <p className="type-body mt-3 max-w-md text-base leading-7 text-ink-dim">
            The playlist snapshot in this share link is malformed, outdated, or too large. Ask for a fresh link, or start a new vibe below.
          </p>
          <Button type="button" onClick={closeSharedPlaylist} size="md" className="mt-6">
            Go to Audelle
          </Button>
        </main>
      ) : shouldRenderSlideshow && result ? (
        <Slideshow
          tracks={result.tracks}
          playlistTitle={text.trim()}
          playlistPrompt={text.trim()}
          playlistSeed={result.seed}
          onMusicReady={markMusicReady}
          onClose={() => {
            setShowSlideshow(false)
            setIsMusicReady(false)
            setStatus('idle')
          }}
        />
      ) : (
      <motion.main
        className="relative mx-auto flex min-h-[100dvh] max-w-4xl flex-col justify-center px-6 py-4 sm:px-10 sm:py-4"
        initial={prefersReducedMotion ? false : { opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.5, ease: 'easeOut' }}
      >
        <div className="max-w-2xl">
          <div className="flex items-center gap-3">
            <img
              src="/audelle-mark.png"
              alt=""
              aria-hidden="true"
              width={36}
              height={40}
              decoding="async"
              className="h-10 w-auto shrink-0 object-contain"
            />
            <p className="label-meta text-ember">Audelle</p>
          </div>
          <h1 className="type-display mt-4 text-4xl leading-[0.96] text-ink sm:text-5xl md:text-6xl">
            Music for the now
          </h1>
          <p className="type-body mt-4 max-w-xl text-base leading-7 text-ink-dim sm:text-lg">
            Tell us your vibe. Audelle will find your playlist
          </p>
        </div>

        <form onSubmit={handleSubmit} className="mt-6" aria-busy={status === 'loading'}>
          <label htmlFor="vibe" className="sr-only">
            Describe the vibe
          </label>
          <div className="ui-surface ui-input-surface relative p-5 sm:p-6">
            <textarea
              ref={textareaRef}
              id="vibe"
              name="vibe"
              value={text}
              onChange={(e) => setText(e.target.value)}
              readOnly={isTyping}
              aria-describedby={isTyping ? 'typing-status' : undefined}
              placeholder="Late-night drive through the city…"
              rows={2}
              className="type-display w-full resize-none overflow-hidden border-0 bg-transparent text-3xl leading-[1.03] text-ink placeholder:text-ink-dim/35 focus:outline-none sm:text-4xl md:text-5xl"
            />
            <AnimatePresence>
              {isTyping && typingPrompt && (
              <motion.div aria-hidden="true" className="absolute inset-0 z-10 flex cursor-wait items-center rounded-2xl bg-surface/90 px-5 sm:px-6" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} transition={{ duration: prefersReducedMotion ? 0 : 0.22 }}>
                <TextEffect
                  per="word"
                  as="p"
                  preset="blur"
                  className="type-display text-3xl leading-[1.03] text-ink sm:text-4xl md:text-5xl"
                  onAnimationComplete={() => finishPrompt(typingPrompt)}
                >
                  {typingPrompt}
                </TextEffect>
              </motion.div>
              )}
            </AnimatePresence>
            <p id="typing-status" className="sr-only" role="status">
              {isTyping ? 'Writing your selected vibe.' : ''}
            </p>
          </div>
          <div className="mt-8 flex flex-wrap items-center justify-between gap-6 border-t border-line pt-6">
            <FiltersPanel disabled={isTyping} filters={filters} invalidYearRange={hasInvalidYearRange} onChange={setFilters} />

            <Button
              type="submit"
              disabled={!text.trim() || status === 'loading' || isTyping}
              size="md"
              className="shrink-0"
            >
              {status === 'loading' ? 'Creating playlist…' : 'Generate playlist →'}
            </Button>
          </div>
        </form>

        <div className="mt-8">
          <p className="label-meta mb-2 text-ink-dim">Or try</p>
          <ul>
            {EXAMPLE_PROMPTS.map((prompt, i) => (
              <motion.li
                key={prompt}
                className="border-t border-line first:border-t-0"
                initial={prefersReducedMotion ? false : { opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.4, delay: 0.15 + i * 0.06, ease: 'easeOut' }}
              >
                <button
                  type="button"
                  onClick={() => typePrompt(prompt)}
                  disabled={isTyping || status === 'loading'}
                  className="ui-list-action group flex min-h-14 w-full items-center gap-4 py-4 text-left focus:outline-none disabled:cursor-wait disabled:opacity-45"
                >
                  <span className="label-meta w-6 shrink-0 text-center text-ink-dim/50 transition-colors group-hover:text-ember">
                    {String(i + 1).padStart(2, '0')}
                  </span>
                  <span className="flex-1 font-display text-lg normal-case text-ink-dim transition-colors group-hover:text-ink sm:text-xl">
                    {prompt}
                  </span>
                </button>
              </motion.li>
            ))}
          </ul>
        </div>

        <div className="mt-6">
          {status === 'error' && (
            <div className="border-t border-line pt-6 text-center" role="alert">
              <p className="text-ink">{errorMessage}</p>
              <Button
                type="button"
                onClick={handleSubmit}
                variant="outline"
                size="sm"
                className="mt-3"
              >
                Retry
              </Button>
            </div>
          )}

          {status === 'done' && result && result.tracks.length === 0 && (
            <p className="text-center text-ink-dim">Nothing matched those filters — try loosening them.</p>
          )}
        </div>
      </motion.main>
      )}
      {isTransitioningToResults && (
        <ResultTransition
          isReady={Boolean(result?.tracks.length) && isMusicReady}
          onCovered={revealSlideshow}
          onComplete={completeResultTransition}
        />
      )}
    </div>
  )
}

export default App
