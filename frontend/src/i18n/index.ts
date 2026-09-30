/**
 * The languages, and only the one currently needed. The others are only loaded when switching.
 *
 * Built in are German and English. There is no fallback language for them: if a text is missing, its key
 * shows up, and `complete.test.ts` makes sure both files have the same entries.
 *
 * Custom languages (uploaded under Settings, Languages) are laid over English instead, so a translation that
 * is not finished, or older than the running version, still shows every text. See `custom.ts`.
 *
 * A new built-in language: put `xx.json` next to the others and add an entry to `LANGUAGES` here.
 */

import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import { merge, type Texts } from './custom'
import { customLanguage, customLanguages } from './customStore'

interface LanguageEntry {
  /** Short, for the switcher. */
  label: string
  /** The name in the language itself, for screen readers and the tooltip. */
  name: string
  load: () => Promise<{ default: Texts }>
}

export const LANGUAGES = {
  de: { label: 'DE', name: 'Deutsch', load: () => import('./de.json') },
  en: { label: 'EN', name: 'English', load: () => import('./en.json') },
} as const satisfies Record<string, LanguageEntry>

export type BuiltInLanguage = keyof typeof LANGUAGES
export const BUILT_IN_LANGUAGES = Object.keys(LANGUAGES) as BuiltInLanguage[]

export interface LanguageChoice {
  code: string
  label: string
  name: string
  builtIn: boolean
}

/** Built-in first, then the custom ones by name. */
export function availableLanguages(): LanguageChoice[] {
  return [
    ...BUILT_IN_LANGUAGES.map((code) => ({ code, label: LANGUAGES[code].label, name: LANGUAGES[code].name, builtIn: true })),
    ...customLanguages().map(({ meta }) => ({ code: meta.code, label: meta.label, name: meta.name, builtIn: false })),
  ]
}

/** If the browser speaks none of the languages. Also what custom languages are laid over. */
const FALLBACK: BuiltInLanguage = 'en'

const STORAGE_KEY = 'nexsift.language'

function isBuiltIn(value: unknown): value is BuiltInLanguage {
  return typeof value === 'string' && value in LANGUAGES
}

export function isLanguage(value: unknown): value is string {
  return isBuiltIn(value) || (typeof value === 'string' && customLanguage(value) !== undefined)
}

/** The stored choice, otherwise the first browser language we have (only the language part counts: `de-AT` is `de`). */
function initialLanguage(): string {
  try {
    const stored = localStorage.getItem(STORAGE_KEY)
    if (isLanguage(stored)) return stored
  } catch {
    // Private mode without localStorage.
  }
  const codes = availableLanguages().map((language) => language.code)
  for (const wanted of navigator.languages ?? [navigator.language]) {
    const exact = codes.find((code) => code.toLowerCase() === wanted.toLowerCase())
    if (exact) return exact
    const primary = wanted.toLowerCase().split(/[-_]/)[0]
    const match = codes.find((code) => code.toLowerCase().split(/[-_]/)[0] === primary)
    if (match) return match
  }
  return FALLBACK
}

async function textsFor(language: string): Promise<Texts> {
  if (isBuiltIn(language)) return (await LANGUAGES[language].load()).default
  const custom = customLanguage(language)
  const english = (await LANGUAGES[FALLBACK].load()).default
  return custom ? merge(english, custom.texts) : english
}

export async function startI18n(): Promise<void> {
  const language = initialLanguage()
  await i18n.use(initReactI18next).init({
    resources: { [language]: { translation: await textsFor(language) } },
    lng: language,
    fallbackLng: false,
    interpolation: { escapeValue: false },
  })
  document.documentElement.lang = language
}

export async function changeLanguage(language: string): Promise<void> {
  if (!isLanguage(language)) return
  try {
    localStorage.setItem(STORAGE_KEY, language)
  } catch {
    // Then the choice only holds until the next reload.
  }
  // Custom languages are always loaded fresh: the file may have been replaced since.
  if (!isBuiltIn(language) || !i18n.hasResourceBundle(language, 'translation')) {
    i18n.addResourceBundle(language, 'translation', await textsFor(language), false, true)
  }
  document.documentElement.lang = language
  await i18n.changeLanguage(language)
}

/** After an upload or removal: show the new texts at once, or fall back to English if the active one is gone. */
export async function refreshCustomLanguage(code: string): Promise<void> {
  if (i18n.language !== code) {
    i18n.removeResourceBundle(code, 'translation')
    return
  }
  if (isLanguage(code)) {
    i18n.addResourceBundle(code, 'translation', await textsFor(code), false, true)
    await i18n.changeLanguage(code)
  } else {
    await changeLanguage(FALLBACK)
  }
}

export default i18n
