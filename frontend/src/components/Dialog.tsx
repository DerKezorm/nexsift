import { useEffect, useId, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'

import { Symbol } from './Symbol'

/**
 * A modal in the middle. Escape and a click beside it close it.
 *
 * Rendered into <body>: a card with backdrop-blur becomes the containing block of every fixed element inside it,
 * and a dialog opened from such a card was cut off at the card's edges.
 */
export function Dialog({ title, onClose, children, wide = false }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  const { t } = useTranslation()
  const id = useId()

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return createPortal(
    <div className="fixed inset-0 z-40 flex items-start justify-center overflow-y-auto bg-scrim p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={id}
        className={'m-auto w-full rounded-2xl border border-ink-700 bg-ink-850 p-6 shadow-2xl shadow-black/50 ' + (wide ? 'max-w-2xl' : 'max-w-lg')}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-5 flex items-center justify-between gap-4">
          <h2 id={id} className="text-lg font-semibold">
            {title}
          </h2>
          <button type="button" onClick={onClose} className="rounded-full p-1.5 text-mist-500 hover:text-mist-100" aria-label={t('common.close')}>
            <Symbol name="close" />
          </button>
        </div>
        {children}
      </div>
    </div>,
    document.body,
  )
}
