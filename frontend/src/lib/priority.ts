import type { Priority } from '../api/types'

const RANK: Record<Priority, number> = { info: 0, warn: 1, crit: 2 }

export function higher(a: Priority, b: Priority): Priority {
  return RANK[a] >= RANK[b] ? a : b
}

export function atLeast(priority: Priority, minimum: Priority): boolean {
  return RANK[priority] >= RANK[minimum]
}

/** Text and dot color per priority. Only these three colors mean something in the list. */
export const PRIORITY_TEXT: Record<Priority, string> = { crit: 'text-crit-500', warn: 'text-warn-500', info: 'text-info-500' }
export const PRIORITY_DOT: Record<Priority, string> = { crit: 'bg-crit-500', warn: 'bg-warn-500', info: 'bg-info-500' }
export const PRIORITY_CHIP: Record<Priority, string> = {
  crit: 'border-crit-500/40 bg-crit-500/10 text-crit-500',
  warn: 'border-warn-500/40 bg-warn-500/10 text-warn-500',
  info: 'border-info-500/40 bg-info-500/10 text-info-500',
}

/** What the server writes into `resolved_by` when a problem is closed in the interface (services/threads.py). */
export const RESOLVED_BY_HAND = 'Marked as done by hand'

/** Warnings and critical problems can be closed by hand while no all-clear came; information has nothing to close. */
export function resolvable(thread: { priority: Priority; resolved_at: string | null }): boolean {
  return !thread.resolved_at && thread.priority !== 'info'
}
