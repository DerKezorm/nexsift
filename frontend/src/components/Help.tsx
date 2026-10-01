import { useEffect, useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'

import { Symbol } from './Symbol'

/** Room the explanation keeps to the edge of the window. */
const EDGE = 8
const WIDTH = 288

/**
 * The small "?" next to a label. A click (or Enter) opens a short explanation right there; a click elsewhere or
 * Escape closes it. Every setting, every field and every section heading gets one: nobody should have to guess
 * what a switch does.
 *
 * The explanation lives at the end of the page and is placed by hand: inside a sidebar that scrolls or at the edge of
 * the window it was cut off, and under an upper-case heading it came out in capitals (seen on 01.10.2026).
 */
export function Help({ children, label }: { children: ReactNode; label?: string }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const [place, setPlace] = useState<{ top: number; left: number; width: number } | null>(null)
  const id = useId()
  const button = useRef<HTMLButtonElement>(null)
  const note = useRef<HTMLSpanElement>(null)

  useLayoutEffect(() => {
    if (!open || !button.current) {
      setPlace(null)
      return
    }
    const rect = button.current.getBoundingClientRect()
    const width = Math.min(WIDTH, window.innerWidth - 2 * EDGE)
    const left = Math.min(Math.max(rect.left + rect.width / 2 - width / 2, EDGE), window.innerWidth - width - EDGE)
    setPlace({ top: rect.bottom + 6, left, width })
  }, [open])

  useEffect(() => {
    if (!open) return
    function close(event: MouseEvent | KeyboardEvent) {
      if (event instanceof KeyboardEvent) {
        if (event.key === 'Escape') setOpen(false)
        return
      }
      const target = event.target as Node
      if (!button.current?.contains(target) && !note.current?.contains(target)) setOpen(false)
    }
    // The explanation sits where the button was; when the page moves, it closes instead of floating elsewhere.
    const away = () => setOpen(false)
    window.addEventListener('mousedown', close)
    window.addEventListener('keydown', close)
    window.addEventListener('resize', away)
    window.addEventListener('scroll', away, true)
    return () => {
      window.removeEventListener('mousedown', close)
      window.removeEventListener('keydown', close)
      window.removeEventListener('resize', away)
      window.removeEventListener('scroll', away, true)
    }
  }, [open])

  return (
    <span className="relative inline-flex align-middle">
      <button
        ref={button}
        type="button"
        onClick={(event) => {
          event.preventDefault()
          event.stopPropagation()
          setOpen(!open)
        }}
        aria-expanded={open}
        aria-controls={id}
        aria-label={label ? t('help.about', { what: label }) : t('help.open')}
        className={
          'inline-flex h-4.5 w-4.5 items-center justify-center rounded-full border text-[10px] leading-none font-bold transition-colors ' +
          (open ? 'border-accent-500 bg-accent-500 text-on-accent' : 'border-ink-600 text-mist-500 hover:border-mist-400 hover:text-mist-200')
        }
      >
        ?
      </button>
      {open &&
        place &&
        createPortal(
          <span
            ref={note}
            id={id}
            role="note"
            style={{ top: place.top, left: place.left, width: place.width }}
            className="fixed z-[60] rounded-xl border border-ink-600 bg-ink-800 p-3 text-left text-xs leading-relaxed font-normal tracking-normal normal-case text-mist-200 shadow-2xl shadow-black/50"
          >
            {children}
          </span>,
          document.body,
        )}
    </span>
  )
}

/** A longer explanation in the flow of a page: a box with an icon, for "how does this work" on top of a section. */
export function Explainer({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <div className="flex gap-3 rounded-xl border border-ink-700 bg-ink-900/70 p-3.5 text-sm text-mist-400">
      <Symbol name="info" className="mt-0.5 h-4 w-4 shrink-0 text-accent-400" />
      <div className="min-w-0">
        {title && <p className="mb-1 font-medium text-mist-200">{title}</p>}
        {children}
      </div>
    </div>
  )
}
