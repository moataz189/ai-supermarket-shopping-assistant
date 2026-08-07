import { useEffect, useState } from 'react'
import { useReducedMotion } from 'framer-motion'

const TYPE_MS = 45
const DELETE_MS = 25
const PAUSE_AFTER_TYPE_MS = 1400
const PAUSE_AFTER_DELETE_MS = 300

/** Cycles through `words`, typing and deleting each in turn. Returns the current
 * partially-typed string. Reduces to the first word, statically, when the user prefers
 * reduced motion. */
export function useTypewriter(words: string[]): string {
  const reduceMotion = useReducedMotion()
  const [text, setText] = useState(reduceMotion ? (words[0] ?? '') : '')

  useEffect(() => {
    if (reduceMotion || words.length === 0) return

    let wordIndex = 0
    let charIndex = 0
    let deleting = false
    let timeoutId: ReturnType<typeof setTimeout>

    function tick() {
      const word = words[wordIndex]
      if (!deleting) {
        charIndex++
        setText(word.slice(0, charIndex))
        if (charIndex === word.length) {
          timeoutId = setTimeout(() => {
            deleting = true
            tick()
          }, PAUSE_AFTER_TYPE_MS)
          return
        }
        timeoutId = setTimeout(tick, TYPE_MS)
      } else {
        charIndex--
        setText(word.slice(0, charIndex))
        if (charIndex === 0) {
          deleting = false
          wordIndex = (wordIndex + 1) % words.length
          timeoutId = setTimeout(tick, PAUSE_AFTER_DELETE_MS)
          return
        }
        timeoutId = setTimeout(tick, DELETE_MS)
      }
    }

    timeoutId = setTimeout(tick, TYPE_MS)
    return () => clearTimeout(timeoutId)
  }, [words, reduceMotion])

  return text
}
