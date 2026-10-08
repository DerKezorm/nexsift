import type { Priority, Target } from '../api/types'
import { atLeast } from './priority'

/**
 * The targets a priority reaches from a source, as the server decides it: switched-off targets never, the source's
 * chosen targets (none of them left: every target), and from the source's level, else each target's own minimum.
 */
export function reached(targets: Target[], chosen: number[], level: Priority | '', priority: Priority): Target[] {
  const enabled = targets.filter((target) => target.enabled)
  const known = targets.some((target) => chosen.includes(target.id))
  return (known ? enabled.filter((target) => chosen.includes(target.id)) : enabled).filter((target) => atLeast(priority, level || target.min_priority))
}
