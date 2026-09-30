import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { Symbol } from './Symbol'

/** A value to paste somewhere else, with a copy button. Multi-line values keep their line breaks. */
export function CopyField({ label, value, multiline = false, hint }: { label?: string; value: string; multiline?: boolean; hint?: ReactNode }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      // Without HTTPS the clipboard may be closed; the value stays selectable.
    }
  }

  return (
    <div className="flex flex-col gap-1">
      {label && <span className="text-xs font-medium text-mist-500">{label}</span>}
      <div className="flex items-start gap-2 rounded-xl border border-ink-700 bg-ink-950/70 py-2 pr-2 pl-3">
        <code className={'ns-scroll min-w-0 flex-1 font-mono text-xs text-mist-200 ' + (multiline ? 'whitespace-pre-wrap' : 'overflow-x-auto whitespace-nowrap')}>{value}</code>
        <button
          type="button"
          onClick={() => void copy()}
          className={'shrink-0 rounded-lg p-1 transition-colors ' + (copied ? 'text-ok-500' : 'text-mist-500 hover:text-mist-100')}
          aria-label={t('common.copy')}
          title={t('common.copy')}
        >
          <Symbol name={copied ? 'check' : 'copy'} className="h-3.5 w-3.5" />
        </button>
      </div>
      {hint && <span className="text-xs text-mist-500">{hint}</span>}
    </div>
  )
}
