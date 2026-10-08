import { describe, expect, it } from 'vitest'

import type { Priority, Target } from '../api/types'
import { reached } from './levels'

function target(id: number, name: string, min_priority: Priority, enabled = true): Target {
  return { id, name, min_priority, enabled, kind: 'ntfy', url: '', chat_id: '', user: '', has_token: false, quiet_from: '', quiet_to: '' } as Target
}

const PHONE = target(1, 'phone', 'warn')
const TELEGRAM = target(2, 'telegram', 'crit')
const OFF = target(3, 'old', 'info', false)
const ALL = [PHONE, TELEGRAM, OFF]
const names = (list: Target[]) => list.map((item) => item.name)

describe('what a source reaches', () => {
  it('goes by each target out of the box', () => {
    expect(names(reached(ALL, [], '', 'info'))).toEqual([])
    expect(names(reached(ALL, [], '', 'warn'))).toEqual(['phone'])
    expect(names(reached(ALL, [], '', 'crit'))).toEqual(['phone', 'telegram'])
  })

  it('lets a level of its own replace the minimum, both ways', () => {
    expect(names(reached(ALL, [], 'info', 'info'))).toEqual(['phone', 'telegram'])
    expect(names(reached(ALL, [], 'crit', 'warn'))).toEqual([])
  })

  it('keeps to the chosen targets, and to all when none of them is left', () => {
    expect(names(reached(ALL, [2], 'info', 'info'))).toEqual(['telegram'])
    expect(names(reached(ALL, [99], 'info', 'info'))).toEqual(['phone', 'telegram'])
    // A switched-off target still counts as chosen, so the source sends nowhere, as on the server.
    expect(names(reached(ALL, [3], 'info', 'crit'))).toEqual([])
  })
})
