/**
 * Where custom languages live. In the mockup: the browser. Later: the server (GET/PUT/DELETE /api/languages),
 * which checks every file again with the same rules before storing it under /data/languages. The interface
 * stays the same, so the settings page and the switcher do not change.
 */

import { useSyncExternalStore } from 'react'

import { merge, type CustomLanguage } from './custom'

const KEY = 'nexsift.languages'
const EVENT = 'nexsift-languages'

function read(): CustomLanguage[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(KEY) ?? '[]') as unknown
    return Array.isArray(parsed) ? (parsed as CustomLanguage[]) : []
  } catch {
    return []
  }
}

let current = read()

function write(next: CustomLanguage[]): void {
  current = next
  try {
    localStorage.setItem(KEY, JSON.stringify(next))
  } catch {
    // Full or blocked: the language holds until the next reload.
  }
  window.dispatchEvent(new Event(EVENT))
}

export function customLanguages(): CustomLanguage[] {
  return current
}

export function customLanguage(code: string): CustomLanguage | undefined {
  return current.find((language) => language.meta.code === code)
}

/**
 * "add" lays the new texts over what is there: that is how a file with only the missing texts completes a
 * language after an update. "replace" throws the old texts away.
 */
export function saveLanguage(language: CustomLanguage, mode: 'add' | 'replace'): CustomLanguage {
  const existing = customLanguage(language.meta.code)
  const saved = existing && mode === 'add' ? { ...language, texts: merge(existing.texts, language.texts) } : language
  write([...current.filter((l) => l.meta.code !== language.meta.code), saved].sort((a, b) => a.meta.name.localeCompare(b.meta.name)))
  return saved
}

export function removeLanguage(code: string): void {
  write(current.filter((language) => language.meta.code !== code))
}

function subscribe(listener: () => void): () => void {
  window.addEventListener(EVENT, listener)
  return () => window.removeEventListener(EVENT, listener)
}

export function useCustomLanguages(): CustomLanguage[] {
  return useSyncExternalStore(subscribe, () => current)
}
