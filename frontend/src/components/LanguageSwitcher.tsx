import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { availableLanguages, changeLanguage } from '../i18n'
import { useCustomLanguages } from '../i18n/customStore'
import { Symbol } from './Symbol'

/** Up to this many languages sit side by side as pills; more open a list, so the header does not grow. */
const PILLS = 3

/** The choice stays in the browser; later it will be tied to the account. Custom languages appear here on their own. */
export function LanguageSwitcher() {
  const { t, i18n } = useTranslation()
  useCustomLanguages() // re-render when one is added or removed
  const languages = availableLanguages()
  const [open, setOpen] = useState(false)
  const box = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function close(event: MouseEvent | KeyboardEvent) {
      if (event instanceof KeyboardEvent ? event.key === 'Escape' : !box.current?.contains(event.target as Node)) setOpen(false)
    }
    window.addEventListener('mousedown', close)
    window.addEventListener('keydown', close)
    return () => {
      window.removeEventListener('mousedown', close)
      window.removeEventListener('keydown', close)
    }
  }, [open])

  if (languages.length <= PILLS) {
    return (
      <div className="flex items-center rounded-full border border-ink-700 bg-ink-850 p-0.5" role="group" aria-label={t('language.label')}>
        {languages.map((language) => {
          const active = i18n.language === language.code
          return (
            <button
              key={language.code}
              type="button"
              lang={language.code}
              aria-label={language.name}
              title={language.name}
              onClick={() => void changeLanguage(language.code)}
              aria-pressed={active}
              className={'rounded-full px-2.5 py-1 text-xs font-semibold transition-colors ' + (active ? 'bg-accent-500 text-on-accent' : 'text-mist-500 hover:text-mist-100')}
            >
              {language.label}
            </button>
          )
        })}
      </div>
    )
  }

  const current = languages.find((language) => language.code === i18n.language) ?? languages[0]
  return (
    <div className="relative" ref={box}>
      <button
        type="button"
        onClick={() => setOpen(!open)}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label={`${t('language.label')}: ${current.name}`}
        className="inline-flex items-center gap-1 rounded-full border border-ink-700 bg-ink-850 py-1.5 pr-2 pl-3 text-xs font-semibold text-mist-300 hover:text-mist-100"
      >
        {current.label}
        <Symbol name="chevronDown" className="h-3.5 w-3.5" />
      </button>
      {open && (
        <ul role="listbox" aria-label={t('language.label')} className="absolute right-0 z-40 mt-2 w-52 rounded-xl border border-ink-700 bg-ink-850 p-1 shadow-2xl shadow-black/50">
          {languages.map((language) => (
            <li key={language.code} role="option" aria-selected={language.code === current.code}>
              <button
                type="button"
                lang={language.code}
                onClick={() => {
                  setOpen(false)
                  void changeLanguage(language.code)
                }}
                className={'flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-sm ' + (language.code === current.code ? 'bg-ink-800 text-mist-100' : 'text-mist-300 hover:bg-ink-800/60')}
              >
                <span className="w-7 font-mono text-xs text-mist-500">{language.label}</span>
                <span className="flex-1 truncate">{language.name}</span>
                {!language.builtIn && <span className="text-[10px] text-mist-600">{t('languages.customShort')}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
