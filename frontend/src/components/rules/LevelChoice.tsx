import { useTranslation } from 'react-i18next'

import type { Priority, Rule, Target } from '../../api/types'
import { reached } from '../../lib/levels'
import { PRIORITY_CHIP } from '../../lib/priority'
import { ruleName } from '../../lib/ruleNames'
import { SelectField } from '../ui'

/** In the order of a target's own choice; the preview starts with the loudest. */
const LEVELS: Priority[] = ['info', 'warn', 'crit']
const DOWNWARDS: Priority[] = ['crit', 'warn', 'info']

/**
 * What reaches the targets from a source or a rule's lines: as each target says (empty), or a level of its own that
 * replaces the targets' minimum, both up and down. A rule's level comes before the source's.
 */
export function LevelChoice({ value, onChange, scope }: { value: Priority | ''; onChange: (value: Priority | '') => void; scope: 'source' | 'rule' }) {
  const { t } = useTranslation()
  return (
    <SelectField label={t(`levels.${scope}Label`)} value={value} onChange={(next) => onChange(next as Priority | '')} help={t(`levels.${scope}Help`)}>
      <option value="">{t(`levels.${scope}Default`)}</option>
      {LEVELS.map((level) => (
        <option key={level} value={level}>
          {t(`levels.${level}`)}
        </option>
      ))}
    </SelectField>
  )
}

/**
 * Under the choice in a source's dialog: which targets each priority reaches, with the source's route and level as
 * they stand in the dialog, and the rules that keep its messages in the inbox whatever is picked here.
 */
export function LevelReach({ targets, chosen, level, rules, sourceId }: { targets: Target[]; chosen: number[]; level: Priority | ''; rules: Rule[]; sourceId: number }) {
  const { t } = useTranslation()
  if (!targets.some((target) => target.enabled)) return null
  const keeping = rules.filter((rule) => rule.enabled && rule.actions.push === 'never' && !rule.actions.drop && (rule.source_id === null || rule.source_id === sourceId))
  return (
    <div className="-mt-2 flex flex-col gap-2 rounded-xl border border-ink-700 bg-ink-900 p-3 text-sm">
      <p className="text-xs font-medium text-mist-400">{t('levels.reachTitle')}</p>
      <ul className="flex flex-col gap-1.5">
        {DOWNWARDS.map((priority) => {
          const names = reached(targets, chosen, level, priority).map((target) => target.name)
          return (
            <li key={priority} className="flex flex-wrap items-baseline gap-2">
              <span className={'w-20 shrink-0 rounded-md border px-1.5 py-px text-center text-xs ' + PRIORITY_CHIP[priority]}>{t(`priority.${priority}`)}</span>
              <span className={names.length ? 'text-mist-100' : 'text-mist-500'}>{names.length ? names.join(', ') : t('levels.nowhere')}</span>
            </li>
          )
        })}
      </ul>
      <p className="text-xs text-mist-500">{t('levels.quiet')}</p>
      {keeping.length > 0 && <p className="text-xs text-warn-500">{t('levels.kept', { names: keeping.map((rule) => t('levels.keptRule', { name: ruleName(t, rule.name) })).join(', ') })}</p>}
    </div>
  )
}
