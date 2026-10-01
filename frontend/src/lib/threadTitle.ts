import type { TFunction } from 'i18next'

import type { ThreadSummary } from '../api/types'

/** A routine line holds different messages, so it is named by their count; any other line by its latest title. */
export function threadTitle(thread: Pick<ThreadSummary, 'routine' | 'title' | 'event_count'>, t: TFunction): string {
  return thread.routine ? t('inbox.routineTitle', { count: thread.event_count }) : thread.title
}
