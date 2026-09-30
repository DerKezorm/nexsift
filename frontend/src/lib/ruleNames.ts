import type { TFunction } from 'i18next'

/**
 * The rules nexsift brings along are stored with English names (the server speaks English to the outside). In
 * the interface they show in the chosen language, as long as nobody renamed them; a renamed rule shows the name
 * its owner gave it.
 */
const BUILT_IN: Record<string, string> = {
  'Words for failures make it critical': 'keywordsCritical',
  'Words for trouble make it a warning': 'keywordsWarning',
  'Watchtower: bundle updates, never push them': 'watchtower',
  'Paperless: bundle new documents, never push them': 'paperless',
  'sshd: failed sign-ins in one line': 'sshd',
}

export function ruleName(t: TFunction, name: string): string {
  const key = BUILT_IN[name]
  return key ? t(`rules.builtInName.${key}`) : name
}
