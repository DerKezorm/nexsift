import type { TFunction } from 'i18next'

import type { ThreadSummary } from '../api/types'
import { textBody, textTitle } from './senderTexts'

type Titled = Pick<ThreadSummary, 'routine' | 'title' | 'event_count'> & Partial<Pick<ThreadSummary, 'texts' | 'title_from_texts'>>

/** A routine line holds different messages, so it is named by their count; any other line by its latest title. */
export function threadTitle(thread: Titled, t: TFunction): string {
  if (thread.routine) return t('inbox.routineTitle', { count: thread.event_count })
  return (thread.title_from_texts && textTitle(t, thread.texts)) || thread.title
}

/** The grey line under the title, in the chosen language when nexsift worded the newest message. */
export function threadPreview(thread: Pick<ThreadSummary, 'routine' | 'preview' | 'texts'>, t: TFunction): string {
  const title = textTitle(t, thread.texts)
  const body = textBody(t, thread.texts)
  if (title === null || body === null) return thread.preview
  // One line: the place and the likely cause side by side.
  const line = body.replaceAll('\n', ' · ')
  return (thread.routine && line ? `${title}: ${line}` : line || title).slice(0, 200)
}
