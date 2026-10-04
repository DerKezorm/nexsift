import type { TFunction } from 'i18next'

import type { Texts, TextSegment } from '../api/types'

/**
 * What nexsift worded itself (Uptime Kuma in plain words, for instance) comes as text keys next to the English
 * title and body. Shown here in the chosen language; the server does the same for pushes (services/texts.py).
 * A language without these keys, like an uploaded one that is older, gets the English the server stored.
 */
const MISSING = '\u0000'

function segment(t: TFunction, part: TextSegment): string | null {
  if ('key' in part) {
    const said = t(part.key, { ...part.args, defaultValue: MISSING })
    return said === MISSING ? null : said
  }
  return part.text
}

export function textTitle(t: TFunction, texts: Texts | null | undefined): string | null {
  return texts?.title ? segment(t, texts.title) : null
}

export function textBody(t: TFunction, texts: Texts | null | undefined): string | null {
  if (!texts?.body) return null
  const lines: string[] = []
  for (const line of texts.body) {
    const parts = line.map((part) => segment(t, part))
    if (parts.some((part) => part === null)) return null
    const joined = parts.filter(Boolean).join(' · ')
    if (joined) lines.push(joined)
  }
  return lines.join('\n')
}
