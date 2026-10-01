import de from '../whatsnew/de.json'
import en from '../whatsnew/en.json'

/**
 * "What's new": an editorial text per version, not a changelog. As in nexbeat, nexdeck and Nexview.
 *
 * ⚠️ An entry needs all four fields (lead, sections, smallTitle, small), every section title, body and where.
 * Without one the entry is dropped silently; in Nexview that happened more than once. `whatsnew.test.ts` guards it,
 * and also that the running version has an entry.
 */
export interface WhatsNewSection {
  title: string
  body: string
  /** Where to find it in the interface. */
  where: string
}

export interface WhatsNewEntry {
  lead: string
  sections: WhatsNewSection[]
  smallTitle: string
  small: string[]
}

type File = { entries: Record<string, unknown> }
export const FILES: Record<string, File> = { de, en }

export function isSection(value: unknown): value is WhatsNewSection {
  if (!value || typeof value !== 'object') return false
  const section = value as Record<string, unknown>
  return typeof section.title === 'string' && typeof section.body === 'string' && typeof section.where === 'string'
}

export function isEntry(value: unknown): value is WhatsNewEntry {
  if (!value || typeof value !== 'object') return false
  const entry = value as Record<string, unknown>
  return (
    typeof entry.lead === 'string' &&
    Array.isArray(entry.sections) &&
    entry.sections.every(isSection) &&
    typeof entry.smallTitle === 'string' &&
    Array.isArray(entry.small) &&
    entry.small.every((line) => typeof line === 'string')
  )
}

export function compareVersions(a: string, b: string): number {
  const left = a.split('.').map(Number)
  const right = b.split('.').map(Number)
  for (let index = 0; index < 3; index++) {
    if ((left[index] ?? 0) !== (right[index] ?? 0)) return (left[index] ?? 0) - (right[index] ?? 0)
  }
  return 0
}

/** The newest version with an entry, at most the running one: a text written ahead never shows early. */
export function latestVersion(running?: string | null): string | null {
  const versions = Object.keys(FILES.en.entries).filter((version) => !running || compareVersions(version, running) <= 0)
  return versions.length ? versions.sort((a, b) => compareVersions(b, a))[0] : null
}

/** All versions with an entry, newest first, up to the running one. */
export function allVersions(running?: string | null): string[] {
  return Object.keys(FILES.en.entries)
    .filter((version) => !running || compareVersions(version, running) <= 0)
    .sort((a, b) => compareVersions(b, a))
}

export function entryFor(version: string, language: string): WhatsNewEntry | null {
  const entry = (FILES[language] ?? FILES.en).entries[version]
  return isEntry(entry) ? entry : null
}

/** Should the window open? Only for a version the account has not seen, and never backwards. */
export function unseen(seen: string | null | undefined, latest: string | null): boolean {
  if (!latest) return false
  return !seen || compareVersions(latest, seen) > 0
}
