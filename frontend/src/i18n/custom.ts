/**
 * Languages made by users: one JSON file per language, the same tree as en.json plus a "_meta" block.
 *
 *   { "_meta": { "code": "fr", "name": "Français", "label": "FR", "author": "…", "madeFor": "0.1.0" },
 *     "common": { "back": "Retour", … }, … }
 *
 * The file is data, never code: only strings, only keys English knows, the same {{placeholders}} as English.
 * What is missing falls back to English, so a half-done translation already works. The server will check with
 * the same rules before it stores anything; this module is the single source of those rules for the interface.
 */

export type Texts = { [key: string]: string | Texts }

export interface LanguageMeta {
  code: string
  /** The name in the language itself, for the switcher and screen readers. */
  name: string
  /** Two or three letters for the switcher. */
  label: string
  author?: string
  /** The nexsift version the file was made for; after an update, new texts show up as missing. */
  madeFor?: string
}

export interface CustomLanguage {
  meta: LanguageMeta
  texts: Texts
  uploadedAt: number
}

export interface Report {
  /** Blocking problems: nothing is stored. */
  errors: string[]
  /** Texts that were left out, key plus reason. They fall back to English. */
  rejected: { key: string; reason: 'placeholders' | 'notText' | 'empty' | 'tooLong' }[]
  /** Keys English does not have (typos, or texts from an older version). Ignored. */
  unknown: string[]
  /** Keys English has and the file does not. */
  missing: string[]
  /** Share of English texts the file covers, 0 to 1. */
  coverage: number
  language?: CustomLanguage
}

/** Larger than any real translation, small enough that nobody fills the disk through this door. */
export const MAX_FILE_BYTES = 512 * 1024
const MAX_TEXT = 2000
const CODE = /^[a-z]{2,3}(-[A-Z]{2}|-[A-Z][a-z]{3})?$/
const PLURAL = /_(zero|one|two|few|many|other)$/

export function flatten(tree: Record<string, unknown>, prefix = ''): Map<string, unknown> {
  const result = new Map<string, unknown>()
  for (const [key, value] of Object.entries(tree)) {
    if (!prefix && key === '_meta') continue
    const path = prefix ? `${prefix}.${key}` : key
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      for (const [inner, innerValue] of flatten(value as Record<string, unknown>, path)) result.set(inner, innerValue)
    } else {
      result.set(path, value)
    }
  }
  return result
}

export function unflatten(flat: Map<string, string>): Texts {
  const tree: Texts = {}
  for (const [path, value] of flat) {
    const parts = path.split('.')
    let node = tree
    for (const part of parts.slice(0, -1)) {
      if (typeof node[part] !== 'object') node[part] = {}
      node = node[part] as Texts
    }
    node[parts[parts.length - 1]] = value
  }
  return tree
}

/** English keys the language does not cover. A plural counts as covered when any of its forms is there. */
function missingKeys(english: Map<string, unknown>, own: Set<string>): string[] {
  const pluralBases = new Set([...own].filter((key) => PLURAL.test(key)).map((key) => key.replace(PLURAL, '')))
  return [...english.keys()].filter((key) => !own.has(key) && !(PLURAL.test(key) && pluralBases.has(key.replace(PLURAL, ''))))
}

function placeholders(text: string): string {
  return [...text.matchAll(/\{\{\s*(\w+)\s*\}\}/g)]
    .map((match) => match[1])
    .sort()
    .join(',')
}

/**
 * Plural forms: English has "x_one" and "x_other", Polish needs "x_few" and "x_many" as well. Every form of a
 * key English pluralizes is allowed, and they are all checked against English "x_other".
 */
function referenceKey(key: string, reference: Map<string, unknown>): string | undefined {
  if (reference.has(key)) return key
  const base = key.replace(PLURAL, '')
  if (base !== key && reference.has(`${base}_other`)) return `${base}_other`
  return undefined
}

/** Checks a file against English. Never throws; everything wrong ends up in the report. */
export function validate(raw: string, reference: Texts, builtIn: string[]): Report {
  const report: Report = { errors: [], rejected: [], unknown: [], missing: [], coverage: 0 }
  if (new Blob([raw]).size > MAX_FILE_BYTES) {
    report.errors.push('tooLarge')
    return report
  }
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    report.errors.push('notJson')
    return report
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    report.errors.push('notJson')
    return report
  }
  const root = parsed as Record<string, unknown>
  const meta = root._meta as Partial<LanguageMeta> | undefined
  if (!meta || typeof meta !== 'object') {
    report.errors.push('noMeta')
    return report
  }
  const code = typeof meta.code === 'string' ? meta.code.trim() : ''
  const name = typeof meta.name === 'string' ? meta.name.trim() : ''
  const label = typeof meta.label === 'string' ? meta.label.trim() : ''
  if (!CODE.test(code)) report.errors.push('badCode')
  else if (builtIn.includes(code)) report.errors.push('builtInCode')
  if (!name || name.length > 40) report.errors.push('badName')
  if (!label || label.length > 3) report.errors.push('badLabel')

  const english = flatten(reference as Record<string, unknown>)
  const own = flatten(root)
  const kept = new Map<string, string>()
  for (const [key, value] of own) {
    const ref = referenceKey(key, english)
    if (!ref) {
      report.unknown.push(key)
      continue
    }
    if (typeof value !== 'string') report.rejected.push({ key, reason: 'notText' })
    else if (!value.trim()) report.rejected.push({ key, reason: 'empty' })
    else if (value.length > MAX_TEXT) report.rejected.push({ key, reason: 'tooLong' })
    else if (placeholders(value) !== placeholders(String(english.get(ref)))) report.rejected.push({ key, reason: 'placeholders' })
    else kept.set(key, value)
  }

  report.missing = missingKeys(english, new Set(kept.keys()))
  report.coverage = english.size === 0 ? 0 : (english.size - report.missing.length) / english.size
  if (kept.size === 0 && report.errors.length === 0) report.errors.push('noTexts')

  if (report.errors.length === 0) {
    report.language = {
      meta: {
        code,
        name,
        label: label.toUpperCase(),
        author: typeof meta.author === 'string' ? meta.author.trim().slice(0, 80) : undefined,
        madeFor: typeof meta.madeFor === 'string' ? meta.madeFor.trim().slice(0, 20) : undefined,
      },
      texts: unflatten(kept),
      uploadedAt: Date.now(),
    }
  }
  return report
}

/** English underneath, the custom texts on top: the bundle i18next gets is always complete. */
export function merge(base: Texts, over: Texts): Texts {
  const result: Texts = { ...base }
  for (const [key, value] of Object.entries(over)) {
    const below = result[key]
    result[key] = typeof value === 'object' && typeof below === 'object' ? merge(below, value) : value
  }
  return result
}

/** The file to start from: every English text, and a _meta block to fill in. */
export function template(reference: Texts, version: string): string {
  const meta: LanguageMeta = { code: 'xx', name: 'Name of the language in itself', label: 'XX', author: '', madeFor: version }
  return JSON.stringify({ _meta: meta, ...reference }, null, 2) + '\n'
}

/** Only what is still missing, in English, to translate after an update and upload again on top. */
export function missingFile(language: CustomLanguage, reference: Texts, version: string): string {
  const english = flatten(reference as Record<string, unknown>)
  const own = new Set(flatten(language.texts as Record<string, unknown>).keys())
  const missing = new Map<string, string>()
  for (const key of missingKeys(english, own)) missing.set(key, String(english.get(key)))
  return JSON.stringify({ _meta: { ...language.meta, madeFor: version }, ...unflatten(missing) }, null, 2) + '\n'
}

export function coverageOf(language: CustomLanguage, reference: Texts): number {
  const english = flatten(reference as Record<string, unknown>)
  const own = new Set(flatten(language.texts as Record<string, unknown>).keys())
  return english.size === 0 ? 0 : (english.size - missingKeys(english, own).length) / english.size
}
