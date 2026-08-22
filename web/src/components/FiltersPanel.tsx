import { useEffect, useId, useRef, useState } from 'react'
import { AnimatePresence, motion, useReducedMotion } from 'motion/react'
import type { Filters } from '../lib/types'
import { Button } from './ui/Button'

const POPULARITY_OPTIONS: { label: string; value: number | undefined }[] = [
  { label: 'Any popularity', value: undefined },
  { label: 'At least some plays', value: 10_000 },
  { label: 'Well known (1M+ plays)', value: 1_000_000 },
  { label: 'Huge hit (10M+ plays)', value: 10_000_000 },
]

interface FiltersPanelProps {
  disabled?: boolean
  filters: Filters
  invalidYearRange: boolean
  onChange: (filters: Filters) => void
}

const FIELD_CLASS = 'ui-field'

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

export function FiltersPanel({ disabled = false, filters, invalidYearRange, onChange }: FiltersPanelProps) {
  const [open, setOpen] = useState(false)
  const [popularityOpen, setPopularityOpen] = useState(false)
  const panelId = useId()
  const titleId = useId()
  const popularityLabelId = useId()
  const popularityListId = useId()
  const yearErrorId = useId()
  const triggerRef = useRef<HTMLButtonElement>(null)
  const dialogRef = useRef<HTMLDivElement>(null)
  const popularityTriggerRef = useRef<HTMLButtonElement>(null)
  const popularityControlRef = useRef<HTMLDivElement>(null)
  const popularityOptionRefs = useRef<(HTMLButtonElement | null)[]>([])
  const prefersReducedMotion = useReducedMotion()

  const update = (patch: Partial<Filters>) => onChange({ ...filters, ...patch })

  const activeCount = [
    filters.yearFrom || filters.yearTo,
    filters.genres.length > 0,
    filters.language,
    filters.minViews,
  ].filter(Boolean).length

  const selectedPopularityIndex = POPULARITY_OPTIONS.findIndex((option) => option.value === filters.minViews)
  const safePopularityIndex = selectedPopularityIndex >= 0 ? selectedPopularityIndex : 0
  const selectedPopularity = POPULARITY_OPTIONS[safePopularityIndex]

  const close = () => {
    setPopularityOpen(false)
    setOpen(false)
    triggerRef.current?.focus()
  }

  const choosePopularity = (value: number | undefined) => {
    update({ minViews: value })
    setPopularityOpen(false)
    requestAnimationFrame(() => popularityTriggerRef.current?.focus())
  }

  const resetFilters = () => {
    onChange({
      genres: [],
      yearFrom: undefined,
      yearTo: undefined,
      language: undefined,
      minViews: undefined,
    })
    setPopularityOpen(false)
  }

  useEffect(() => {
    if (!open) return

    const dialog = dialogRef.current
    const first = dialog?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR)
    first?.focus()
    const previousBodyOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'

    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        e.stopPropagation()
        if (dialog?.querySelector('[role="listbox"]')) {
          setPopularityOpen(false)
          popularityTriggerRef.current?.focus()
        } else {
          close()
        }
        return
      }
      if (e.key !== 'Tab' || !dialog) return

      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR))
      if (focusable.length === 0) return
      const firstEl = focusable[0]
      const lastEl = focusable[focusable.length - 1]

      if (e.shiftKey && document.activeElement === firstEl) {
        e.preventDefault()
        lastEl.focus()
      } else if (!e.shiftKey && document.activeElement === lastEl) {
        e.preventDefault()
        firstEl.focus()
      }
    }

    document.addEventListener('keydown', handleKeyDown, true)
    return () => {
      document.removeEventListener('keydown', handleKeyDown, true)
      document.body.style.overflow = previousBodyOverflow
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  useEffect(() => {
    if (!popularityOpen) return
    popularityOptionRefs.current[safePopularityIndex]?.focus()
  }, [popularityOpen, safePopularityIndex])

  useEffect(() => {
    if (!popularityOpen) return

    function closeWhenPointerLeaves(event: PointerEvent) {
      if (!popularityControlRef.current?.contains(event.target as Node)) setPopularityOpen(false)
    }

    document.addEventListener('pointerdown', closeWhenPointerLeaves, true)
    return () => document.removeEventListener('pointerdown', closeWhenPointerLeaves, true)
  }, [popularityOpen])

  function handlePopularityKeyDown(e: React.KeyboardEvent<HTMLButtonElement>, index: number) {
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      popularityOptionRefs.current[(index + 1) % POPULARITY_OPTIONS.length]?.focus()
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      popularityOptionRefs.current[(index - 1 + POPULARITY_OPTIONS.length) % POPULARITY_OPTIONS.length]?.focus()
    } else if (e.key === 'Home') {
      e.preventDefault()
      popularityOptionRefs.current[0]?.focus()
    } else if (e.key === 'End') {
      e.preventDefault()
      popularityOptionRefs.current[POPULARITY_OPTIONS.length - 1]?.focus()
    }
  }

  return (
    <div>
      <Button
        ref={triggerRef}
        type="button"
        disabled={disabled}
        onClick={() => setOpen(true)}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={panelId}
        variant="ghost"
        size="sm"
        className="text-ink-dim disabled:cursor-wait disabled:opacity-45"
      >
        <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
          <path d="M4 7h10M18 7h2M4 17h2M10 17h10M4 12h4M12 12h8" strokeLinecap="round" />
          <circle cx="16" cy="7" r="2" fill="var(--color-canvas)" />
          <circle cx="8" cy="12" r="2" fill="var(--color-canvas)" />
          <circle cx="8" cy="17" r="2" fill="var(--color-canvas)" />
        </svg>
        Filters
        {activeCount > 0 && (
          <span className="ui-button__badge">{activeCount}</span>
        )}
      </Button>

      <AnimatePresence>
        {open && (
          <>
            <motion.div
              aria-hidden="true"
              onClick={close}
              className="ui-overlay fixed inset-0 z-30"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: prefersReducedMotion ? 0 : 0.2 }}
            />
            <motion.div
              ref={dialogRef}
              id={panelId}
              role="dialog"
              aria-modal="true"
              aria-labelledby={titleId}
              className="ui-dialog filters-dialog fixed inset-x-0 bottom-0 z-30 max-h-[85vh] overflow-y-auto border-t border-line bg-canvas p-6 sm:inset-0 sm:m-auto sm:h-fit sm:w-[32rem] sm:border"
              initial={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, y: 24 }}
              animate={{ opacity: 1, y: 0 }}
              exit={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, y: 24 }}
              transition={{ duration: prefersReducedMotion ? 0 : 0.25, ease: 'easeOut' }}
            >
              <div className="mb-5 flex items-center justify-between gap-3">
                <h2 id={titleId} className="label-meta text-ink">
                  Filters
                </h2>
                <div className="flex items-center gap-1">
                  <Button
                    type="button"
                    onClick={resetFilters}
                    variant="ghost"
                    size="sm"
                    className="px-3 text-ink-dim hover:text-ember"
                  >
                    Reset filters
                  </Button>
                  <Button
                    type="button"
                    onClick={close}
                    aria-label="Close filters"
                    variant="surface"
                    size="icon-sm"
                    className="text-ink-dim hover:text-ember"
                  >
                    <svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" className="h-4 w-4">
                      <path d="m7 7 10 10M17 7 7 17" strokeLinecap="round" />
                    </svg>
                  </Button>
                </div>
              </div>

              <div className="grid gap-5 sm:grid-cols-2">
                <div>
                  <label className="label-meta mb-2 block text-ink-dim" htmlFor="year-from">
                    Year range
                  </label>
                  <div className="flex items-center gap-2">
                    <input
                      id="year-from"
                      name="year_from"
                      type="number"
                      inputMode="numeric"
                      min="1"
                      max="2100"
                      placeholder="From"
                      value={filters.yearFrom ?? ''}
                      onChange={(e) => update({ yearFrom: e.target.value ? Number(e.target.value) : undefined })}
                      aria-invalid={invalidYearRange}
                      aria-describedby={invalidYearRange ? yearErrorId : undefined}
                      className={FIELD_CLASS}
                    />
                    <span className="text-ink-dim">–</span>
                    <input
                      type="number"
                      inputMode="numeric"
                      min="1"
                      max="2100"
                      placeholder="To"
                      aria-label="Year to"
                      name="year_to"
                      value={filters.yearTo ?? ''}
                      onChange={(e) => update({ yearTo: e.target.value ? Number(e.target.value) : undefined })}
                      aria-invalid={invalidYearRange}
                      aria-describedby={invalidYearRange ? yearErrorId : undefined}
                      className={FIELD_CLASS}
                    />
                  </div>
                  {invalidYearRange && (
                    <p id={yearErrorId} className="mt-2 text-xs text-ember" role="alert">
                      End year must be the same as or later than the start year.
                    </p>
                  )}
                </div>

                <div>
                  <label className="label-meta mb-2 block text-ink-dim" htmlFor="genre">
                    Genre
                  </label>
                  <input
                    id="genre"
                    name="genre"
                    type="text"
                    placeholder="e.g. jazz, synthwave"
                    maxLength={64}
                    value={filters.genres[0] ?? ''}
                    onChange={(e) => update({ genres: e.target.value ? [e.target.value] : [] })}
                    className={FIELD_CLASS}
                  />
                </div>

                <div>
                  <label className="label-meta mb-2 block text-ink-dim" htmlFor="language">
                    Language
                  </label>
                  <input
                    id="language"
                    name="language"
                    type="text"
                    placeholder="e.g. korean, spanish"
                    maxLength={64}
                    value={filters.language ?? ''}
                    onChange={(e) => update({ language: e.target.value || undefined })}
                    className={FIELD_CLASS}
                  />
                </div>

                <div
                  ref={popularityControlRef}
                  className={`relative ${popularityOpen ? 'z-10' : ''}`}
                  onBlur={(event) => {
                    if (!event.currentTarget.contains(event.relatedTarget)) setPopularityOpen(false)
                  }}
                >
                  <p id={popularityLabelId} className="label-meta mb-2 block text-ink-dim">
                    Popularity
                  </p>
                  <button
                    ref={popularityTriggerRef}
                    type="button"
                    aria-label={`Popularity: ${selectedPopularity.label}`}
                    aria-haspopup="listbox"
                    aria-expanded={popularityOpen}
                    aria-controls={popularityListId}
                    onClick={() => setPopularityOpen((isOpen) => !isOpen)}
                    onKeyDown={(e) => {
                      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
                        e.preventDefault()
                        setPopularityOpen(true)
                      }
                    }}
                    className="ui-field flex min-h-10 items-center justify-between text-left"
                  >
                    <span>{selectedPopularity.label}</span>
                    <svg
                      aria-hidden="true"
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth="1.8"
                      className={`h-4 w-4 text-ember transition-transform ${popularityOpen ? 'rotate-180' : ''}`}
                    >
                      <path d="m6 9 6 6 6-6" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  </button>

                  <AnimatePresence>
                    {popularityOpen && (
                      <motion.div
                        id={popularityListId}
                        role="listbox"
                        aria-labelledby={popularityLabelId}
                        className="ui-menu absolute bottom-full left-0 right-0 z-50 mb-2 overflow-hidden p-1"
                        initial={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, y: 4 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={prefersReducedMotion ? { opacity: 0 } : { opacity: 0, y: 4 }}
                        transition={{ duration: prefersReducedMotion ? 0 : 0.15, ease: 'easeOut' }}
                      >
                        {POPULARITY_OPTIONS.map((option, index) => {
                          const selected = option.value === filters.minViews
                          return (
                            <button
                              key={option.label}
                              ref={(element) => {
                                popularityOptionRefs.current[index] = element
                              }}
                              type="button"
                              role="option"
                              aria-selected={selected}
                              data-popularity-value={option.value ?? ''}
                              onClick={() => choosePopularity(option.value)}
                              onKeyDown={(e) => handlePopularityKeyDown(e, index)}
                              className={`ui-menu-option flex w-full items-center ${
                                selected ? 'ui-menu-option--selected' : ''
                              }`}
                            >
                              {option.label}
                            </button>
                          )
                        })}
                      </motion.div>
                    )}
                  </AnimatePresence>
                </div>
              </div>

              <Button
                type="button"
                onClick={close}
                variant="primary"
                size="md"
                className="mt-6 w-full"
              >
                Apply filters
              </Button>
            </motion.div>
          </>
        )}
      </AnimatePresence>
    </div>
  )
}
