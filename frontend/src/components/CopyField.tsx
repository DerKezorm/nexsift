import { useRef, useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

import { Symbol } from './Symbol'

/**
 * Copies with the modern clipboard where the browser allows it, and with the old way otherwise.
 *
 * The modern one only exists in a secure context: HTTPS or localhost. nexsift is often opened as
 * http://<address>:8490 in the home network, and there navigator.clipboard is simply missing; the button did
 * nothing at all. The old way (a hidden text field, select, execCommand) still works there.
 */
async function copyText(text: string): Promise<boolean> {
  if (window.isSecureContext && navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // Refused (permissions); try the old way below.
    }
  }
  const field = document.createElement('textarea')
  field.value = text
  field.setAttribute('readonly', '')
  field.style.position = 'fixed'
  field.style.top = '-1000px'
  field.style.opacity = '0'
  document.body.appendChild(field)
  field.select()
  let ok: boolean
  try {
    ok = document.execCommand('copy')
  } catch {
    ok = false
  }
  document.body.removeChild(field)
  return ok
}

/** A value to paste somewhere else, with a copy button. Multi-line values keep their line breaks. */
export function CopyField({ label, value, multiline = false, hint }: { label?: string; value: string; multiline?: boolean; hint?: ReactNode }) {
  const { t } = useTranslation()
  const [state, setState] = useState<'idle' | 'copied' | 'failed'>('idle')
  const code = useRef<HTMLElement>(null)

  async function copy() {
    const ok = await copyText(value)
    if (!ok && code.current) {
      // Nothing worked: select the text, so Ctrl+C is all that is left to do.
      const range = document.createRange()
      range.selectNodeContents(code.current)
      window.getSelection()?.removeAllRanges()
      window.getSelection()?.addRange(range)
    }
    setState(ok ? 'copied' : 'failed')
    window.setTimeout(() => setState('idle'), ok ? 1500 : 4000)
  }

  return (
    <div className="flex flex-col gap-1">
      {label && <span className="text-xs font-medium text-mist-500">{label}</span>}
      <div className="flex items-start gap-2 rounded-xl border border-ink-700 bg-ink-950/70 py-2 pr-2 pl-3">
        <code ref={code} className={'ns-scroll min-w-0 flex-1 font-mono text-xs text-mist-200 ' + (multiline ? 'whitespace-pre-wrap' : 'overflow-x-auto whitespace-nowrap')}>
          {value}
        </code>
        <button
          type="button"
          onClick={() => void copy()}
          className={'flex shrink-0 items-center gap-1 rounded-lg p-1 text-xs transition-colors ' + (state === 'copied' ? 'text-ok-500' : state === 'failed' ? 'text-warn-500' : 'text-mist-500 hover:text-mist-100')}
          aria-label={t('common.copy')}
          title={t('common.copy')}
        >
          <Symbol name={state === 'copied' ? 'check' : 'copy'} className="h-3.5 w-3.5" />
          {state === 'copied' && <span>{t('common.copied')}</span>}
          {state === 'failed' && <span>{t('common.copyFailed')}</span>}
        </button>
      </div>
      {hint && <span className="text-xs text-mist-500">{hint}</span>}
    </div>
  )
}
