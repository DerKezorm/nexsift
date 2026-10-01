import { useEffect } from 'react'
import { createPortal } from 'react-dom'
import { useTranslation } from 'react-i18next'

import type { WhatsNewEntry } from '../lib/whatsnew'
import { Button } from './ui'

/** The "What's new" window of one version. One way out ("Got it"), plus Escape and a click beside it. */
export function WhatsNewDialog({ version, entry, onClose }: { version: string; entry: WhatsNewEntry; onClose: () => void }) {
  const { t } = useTranslation()

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      document.body.style.overflow = previous
    }
  }, [onClose])

  const title = t('whatsNew.title', { version })
  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-scrim p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={title}
      onClick={(event) => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <div className="flex max-h-[85vh] w-full max-w-lg flex-col rounded-2xl border border-ink-700 bg-ink-850 shadow-2xl shadow-black/60">
        <h2 className="border-b border-ink-700 px-6 py-4 text-lg font-bold tracking-tight">{title}</h2>
        <div className="overflow-y-auto px-6 py-4 text-sm">
          <p className="mb-4 leading-relaxed text-mist-300">{entry.lead}</p>
          {entry.sections.map((section) => (
            <section key={section.title} className="mb-4">
              <h3 className="font-semibold text-mist-100">{section.title}</h3>
              <p className="mt-0.5 leading-relaxed text-mist-400">{section.body}</p>
              <p className="mt-0.5 text-[11px] text-mist-600">{section.where}</p>
            </section>
          ))}
          {entry.small.length > 0 && (
            <>
              <h3 className="mt-2 font-semibold text-mist-100">{entry.smallTitle}</h3>
              <ul className="mt-1 list-disc pl-5 text-mist-400">
                {entry.small.map((line) => (
                  <li key={line}>{line}</li>
                ))}
              </ul>
            </>
          )}
        </div>
        <div className="flex justify-end border-t border-ink-700 px-6 py-3">
          <Button onClick={onClose} autoFocus>
            {t('whatsNew.gotIt')}
          </Button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
