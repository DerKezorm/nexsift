import { useTranslation } from 'react-i18next'

import { Symbol } from '../Symbol'

const SHORTCUTS: { keys: string[]; label: string }[] = [
  { keys: ['j', 'k'], label: 'nextPrev' },
  { keys: ['Enter'], label: 'open' },
  { keys: ['e'], label: 'archive' },
  { keys: ['u'], label: 'read' },
  { keys: ['d'], label: 'delete' },
  { keys: ['m'], label: 'mute' },
  { keys: ['o'], label: 'link' },
  { keys: ['/'], label: 'search' },
  { keys: ['1', '4'], label: 'views' },
  { keys: ['?'], label: 'help' },
]

export function ShortcutHelp({ onClose }: { onClose: () => void }) {
  const { t } = useTranslation()
  return (
    <div className="fixed inset-0 z-40 flex items-center justify-center bg-scrim p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="shortcut-title"
        className="w-full max-w-md rounded-2xl border border-ink-700 bg-ink-850 p-6 shadow-2xl shadow-black/50"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h2 id="shortcut-title" className="flex items-center gap-2 text-lg font-semibold">
            <Symbol name="keyboard" />
            {t('shortcuts.title')}
          </h2>
          <button type="button" onClick={onClose} className="rounded-full p-1.5 text-mist-500 hover:text-mist-100" aria-label={t('common.close')}>
            <Symbol name="close" />
          </button>
        </div>
        <dl className="grid grid-cols-[auto_1fr] items-center gap-x-5 gap-y-2.5 text-sm">
          {SHORTCUTS.map(({ keys, label }) => (
            <div key={label} className="contents">
              <dt className="flex items-center gap-1">
                {keys.map((key, index) => (
                  <span key={key} className="flex items-center gap-1">
                    {index > 0 && <span className="text-xs text-mist-600">{label === 'views' ? '…' : '/'}</span>}
                    <kbd>{key}</kbd>
                  </span>
                ))}
              </dt>
              <dd className="text-mist-300">{t(`shortcuts.${label}`)}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  )
}
