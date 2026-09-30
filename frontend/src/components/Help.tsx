import { useEffect, useId, useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { Symbol } from './Symbol'

/**
 * The small "?" next to a label. A click (or Enter) opens a short explanation right there; a click elsewhere or
 * Escape closes it. Every setting, every field and every section heading gets one: nobody should have to guess
 * what a switch does.
 */
export function Help({ children, label }: { children: ReactNode; label?: string }) {
  const { t } = useTranslation()
  const [open, setOpen] = useState(false)
  const id = useId()
  const box = useRef<HTMLSpanElement>(null)

  useEffect(() => {
    if (!open) return
    function close(event: MouseEvent | KeyboardEvent) {
      if (event instanceof KeyboardEvent) {
        if (event.key === 'Escape') setOpen(false)
        return
      }
      if (!box.current?.contains(event.target as Node)) setOpen(false)
    }
    window.addEventListener('mousedown', close)
    window.addEventListener('keydown', close)
    return () => {
      window.removeEventListener('mousedown', close)
      window.removeEventListener('keydown', close)
    }
  }, [open])

  return (
    <span className="relative inline-flex align-middle" ref={box}>
      <button
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
      {open && (
        <span
          id={id}
          role="note"
          className="absolute top-6 left-1/2 z-50 w-72 max-w-[80vw] -translate-x-1/2 rounded-xl border border-ink-600 bg-ink-800 p-3 text-left text-xs leading-relaxed font-normal text-mist-200 shadow-2xl shadow-black/50"
        >
          {children}
        </span>
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
