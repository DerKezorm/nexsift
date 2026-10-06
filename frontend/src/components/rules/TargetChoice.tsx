import { useId, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { useTargets } from '../../lib/data'
import { PRIORITY_CHIP } from '../../lib/priority'
import { Help } from '../Help'

/**
 * Which targets a source's or a rule's pushes go to. Nothing ticked means every target (source) or the source's
 * choice (rule); a target's own minimum and quiet hours still count. Ids of targets deleted since are dropped.
 */
export function TargetChoice({ value, onChange, scope }: { value: number[]; onChange: (value: number[]) => void; scope: 'source' | 'rule' }) {
  const { t } = useTranslation()
  const targets = useTargets()
  const name = useId()
  const known = (targets.data ?? []).filter((target) => value.includes(target.id)).map((target) => target.id)
  const [only, setOnly] = useState(value.length > 0)

  function choose(next: boolean) {
    setOnly(next)
    if (!next) onChange([])
  }

  function tick(id: number, checked: boolean) {
    onChange(checked ? [...known, id] : known.filter((item) => item !== id))
  }

  const label = t('targets.choice.label')
  return (
    <fieldset className="flex flex-col gap-2">
      <legend className="mb-1.5 flex items-center gap-1.5 text-sm font-medium text-mist-300">
        {label}
        <Help label={label}>{t(`targets.choice.${scope}Help`)}</Help>
      </legend>
      {targets.data?.length === 0 ? (
        <p className="text-xs text-mist-500">{t('targets.choice.noTargets')}</p>
      ) : (
        <div className="flex flex-col gap-2 rounded-xl border border-ink-700 bg-ink-900 p-3">
          {([false, true] as const).map((option) => (
            <label key={String(option)} className="flex cursor-pointer items-start gap-2.5 text-sm">
              <input type="radio" name={name} checked={only === option} onChange={() => choose(option)} className="mt-1 accent-accent-500" />
              <span className="text-mist-100">{option ? t('targets.choice.only') : t(`targets.choice.${scope}All`)}</span>
            </label>
          ))}
          {only && (
            <ul className="ml-6 flex flex-col gap-1.5 border-l border-ink-700 pl-3">
              {targets.data?.map((target) => (
                <li key={target.id}>
                  <label className={'flex cursor-pointer flex-wrap items-center gap-2 text-sm ' + (target.enabled ? '' : 'opacity-55')}>
                    <input type="checkbox" checked={known.includes(target.id)} onChange={(event) => tick(target.id, event.target.checked)} className="accent-accent-500" />
                    <span className="text-mist-100">{target.name}</span>
                    <span className="text-xs text-mist-500">{t(`targets.kind.${target.kind}`)}</span>
                    <span className={'rounded-md border px-1.5 py-px text-xs ' + PRIORITY_CHIP[target.min_priority]}>
                      {t('targets.from')} {t(`priority.${target.min_priority}`)}
                    </span>
                    {!target.enabled && <span className="text-xs text-mist-500">{t('targets.choice.off')}</span>}
                  </label>
                </li>
              ))}
            </ul>
          )}
          {only && known.length === 0 && <p className="text-xs text-warn-500">{t(`targets.choice.${scope}NoneTicked`)}</p>}
        </div>
      )}
    </fieldset>
  )
}
