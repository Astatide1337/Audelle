import { useRef } from 'react'
import { motion, useReducedMotion } from 'motion/react'

type TextElement = 'span' | 'p' | 'h1' | 'h2' | 'h3'

interface TextEffectProps {
  children: string
  className?: string
  per?: 'word'
  as?: TextElement
  preset?: 'blur'
  onAnimationComplete?: () => void
}

/** A compact local version of the motion-primitives word reveal API. */
export function TextEffect({
  children,
  className,
  per = 'word',
  as: Component = 'span',
  preset = 'blur',
  onAnimationComplete,
}: TextEffectProps) {
  const prefersReducedMotion = useReducedMotion()
  const completed = useRef(false)
  const words = per === 'word' ? children.trim().split(/\s+/) : [children]

  const finish = () => {
    if (completed.current) return
    completed.current = true
    onAnimationComplete?.()
  }

  return (
    <Component className={className} aria-label={children}>
      {words.map((word, index) => (
        <motion.span
          key={`${word}-${index}`}
          aria-hidden="true"
          className="mr-[0.28em] inline-block last:mr-0"
          initial={prefersReducedMotion ? false : preset === 'blur' ? { opacity: 0, filter: 'blur(8px)', y: 6 } : { opacity: 0 }}
          animate={{ opacity: 1, filter: 'blur(0px)', y: 0 }}
          transition={{ duration: prefersReducedMotion ? 0 : 0.28, delay: prefersReducedMotion ? 0 : index * 0.1, ease: 'easeOut' }}
          onAnimationComplete={index === words.length - 1 ? finish : undefined}
        >
          {word}
        </motion.span>
      ))}
    </Component>
  )
}
