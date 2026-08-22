import { useEffect, useRef, useState } from 'react'
import gsap from 'gsap'
import { motion, useReducedMotion } from 'motion/react'

interface ResultTransitionProps {
  /** Reveal only after the playlist is mounted and its player is ready. */
  isReady: boolean
  onCovered: () => void
  onComplete: () => void
}

// These are the original Codrops vertical path stages, recolored for Audelle.
const paths = {
  step1: {
    unfilled: 'M 0 100 V 100 Q 50 100 100 100 V 100 z',
    inBetween: 'M 0 100 V 50 Q 50 0 100 50 V 100 z',
    filled: 'M 0 100 V 0 Q 50 0 100 0 V 100 z',
  },
  step2: {
    filled: 'M 0 0 V 100 Q 50 100 100 100 V 0 z',
    inBetween: 'M 0 0 V 50 Q 50 0 100 50 V 0 z',
    unfilled: 'M 0 0 V 0 Q 50 0 100 0 V 0 z',
  },
}

export function ResultTransition({ isReady, onCovered, onComplete }: ResultTransitionProps) {
  const pathRef = useRef<SVGPathElement>(null)
  const readyRef = useRef(isReady)
  const coveredRef = useRef(false)
  const revealingRef = useRef(false)
  const revealRef = useRef<(() => void) | null>(null)
  const [isRevealing, setIsRevealing] = useState(false)
  const prefersReducedMotion = useReducedMotion()

  useEffect(() => {
    readyRef.current = isReady
    if (isReady && coveredRef.current) revealRef.current?.()
    if (prefersReducedMotion && isReady) {
      onCovered()
      onComplete()
    }
  }, [isReady, onComplete, onCovered, prefersReducedMotion])

  useEffect(() => {
    const path = pathRef.current
    if (!path) return

    if (prefersReducedMotion) return

    const reveal = () => {
      if (revealingRef.current || !pathRef.current) return
      revealingRef.current = true
      setIsRevealing(true)
      onCovered()

      gsap
        .timeline({ onComplete })
        .set(path, { attr: { d: paths.step2.filled } })
        .to(path, { duration: 0.2, ease: 'sine.in', attr: { d: paths.step2.inBetween } })
        .to(path, { duration: 1, ease: 'power4', attr: { d: paths.step2.unfilled } })
    }
    revealRef.current = reveal

    const cover = gsap.timeline({
      onComplete: () => {
        coveredRef.current = true
        if (readyRef.current) reveal()
      },
    })
    cover
      .set(path, { attr: { d: paths.step1.unfilled } })
      .to(path, { duration: 0.8, ease: 'power4.in', attr: { d: paths.step1.inBetween } }, 0)
      .to(path, { duration: 0.2, ease: 'power1', attr: { d: paths.step1.filled } }, 0.8)

    return () => {
      cover.kill()
      revealRef.current = null
    }
  }, [onComplete, onCovered, prefersReducedMotion])

  return (
    <div className="result-transition pointer-events-auto fixed inset-0 z-50 bg-canvas/10" aria-live="polite">
      <svg aria-hidden="true" className="pointer-events-none absolute inset-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
        <path ref={pathRef} vectorEffect="non-scaling-stroke" fill="var(--color-ember)" d={paths.step1.unfilled} />
      </svg>
      {!isRevealing && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <p className="label-meta flex text-canvas" aria-label="Creating playlist">
            {Array.from('Creating playlist').map((character, index) => (
              <motion.span
                key={`${character}-${index}`}
                aria-hidden="true"
                className={character === ' ' ? 'w-[0.45em]' : undefined}
                animate={prefersReducedMotion ? undefined : { y: [0, -8, 0] }}
                transition={prefersReducedMotion ? undefined : {
                  duration: 0.65,
                  delay: index * 0.04,
                  ease: [0.22, 1, 0.36, 1],
                  repeat: Infinity,
                  repeatDelay: 0.4,
                }}
              >
                {character === ' ' ? '\u00a0' : character}
              </motion.span>
            ))}
          </p>
        </div>
      )}
    </div>
  )
}
