import { useEffect, useState, type ChangeEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { useLocation } from 'react-router-dom'

import { api, errorMessage } from '../api/client'
import type { Condition, Priority, PushMode, Rule, RuleActions, Settings, Source } from '../api/types'
import { Dialog } from '../components/Dialog'
import { Explainer, Help } from '../components/Help'
import { IconField, IconPicker } from '../components/IconPicker'
import { useNotice } from '../components/Notice'
import { SourceMark } from '../components/SourceMark'
import { Symbol } from '../components/Symbol'
import { Badge, Banner, Button, Field, INPUT_CLASS, PageHeader, Section, SelectField, Switch } from '../components/ui'
import { Targets } from '../components/rules/Targets'
import { LANGUAGES } from '../i18n'
import { useSources } from '../lib/data'
import { iconPreview } from '../lib/icons'
import { PRIORITY_CHIP } from '../lib/priority'
import { ruleName } from '../lib/ruleNames'
import { useLoad } from '../lib/useLoad'

const PRIORITIES: Priority[] = ['info', 'warn', 'crit']
const PUSH_MODES: PushMode[] = ['immediate', 'window', 'single', 'never']
/** The languages the server can write pushes in (backend/app/texts). */
const PUSH_LANGUAGES: Settings['push_language'][] = ['de', 'en']

type Draft = Omit<Rule, 'id' | 'position' | 'built_in'> & { id?: number; built_in?: string }

export function RulesPage() {
  const { t } = useTranslation()
  const notify = useNotice()
  const rules = useLoad(() => api.get<Rule[]>('/api/rules'), [])
  const sources = useSources()
  const [editing, setEditing] = useState<Draft | null>(null)
  const location = useLocation()

  // "/rules#targets" from the inbox lands on the targets.
  useEffect(() => {
    if (location.hash === '#targets') document.getElementById('targets')?.scrollIntoView({ block: 'start' })
  }, [location.hash])

  async function move(index: number, step: number) {
    const list = [...(rules.data ?? [])]
    const [rule] = list.splice(index, 1)
    list.splice(index + step, 0, rule)
    rules.set(list)
    try {
      rules.set(await api.put<Rule[]>('/api/rules/order', { ids: list.map((item) => item.id) }))
    } catch (caught) {
      notify({ text: errorMessage(caught) })
      void rules.reload()
    }
  }

  async function toggle(rule: Rule, enabled: boolean) {
    try {
      const saved = await api.put<Rule>(`/api/rules/${rule.id}`, { ...rule, enabled })
      rules.set((rules.data ?? []).map((item) => (item.id === rule.id ? saved : item)))
    } catch (caught) {
      notify({ text: errorMessage(caught) })
    }
  }

  return (
    <>
      <PageHeader
        title={t('rules.title')}
        lead={t('rules.lead')}
        aside={
          <Button onClick={() => setEditing({ name: '', enabled: true, source_id: null, conditions: [{ field: 'any', op: 'word', value: '' }], actions: {} })}>
            <Symbol name="plus" />
            {t('rules.add')}
          </Button>
        }
      />

      <div className="grid gap-6 xl:grid-cols-[1fr_24rem]">
        <div className="flex flex-col gap-6">
          <Section title={t('rules.list.title')} intro={t('rules.list.intro')} help={t('rules.list.help')}>
            {rules.error && <Banner tone="bad">{rules.error}</Banner>}
            <ol className="flex flex-col gap-2">
              {(rules.data ?? []).map((rule, index, list) => (
                <RuleRow
                  key={rule.id}
                  rule={rule}
                  index={index}
                  last={index === list.length - 1}
                  source={sources.data?.find((source) => source.id === rule.source_id)}
                  onToggle={(enabled) => void toggle(rule, enabled)}
                  onMove={(step) => void move(index, step)}
                  onEdit={() => setEditing(rule)}
                />
              ))}
            </ol>
          </Section>

          <div id="targets" className="scroll-mt-24">
            <Targets />
          </div>
        </div>

        <div className="flex flex-col gap-6">
          <Tester sources={sources.data ?? []} />
          <Defaults />
        </div>
      </div>

      {editing && (
        <RuleEditor
          rule={editing}
          sources={sources.data ?? []}
          onSaved={() => {
            setEditing(null)
            void rules.reload()
          }}
          onClose={() => setEditing(null)}
        />
      )}
    </>
  )
}

function RuleRow({
  rule,
  index,
  last,
  source,
  onToggle,
  onMove,
  onEdit,
}: {
  rule: Rule
  index: number
  last: boolean
  source?: Source
  onToggle: (enabled: boolean) => void
  onMove: (step: number) => void
  onEdit: () => void
}) {
  const { t } = useTranslation()
  return (
    <li className={'flex items-start gap-3 rounded-xl border border-ink-700 bg-ink-900 p-3 ' + (rule.enabled ? '' : 'opacity-55')}>
      <span className="mt-1 w-5 shrink-0 text-right font-mono text-xs text-mist-600 tabular-nums">{index + 1}</span>
      <button type="button" onClick={onEdit} className="min-w-0 flex-1 text-left" title={t('rules.editHint')}>
        <p className="flex flex-wrap items-center gap-2 text-sm font-medium text-mist-100">
          {ruleName(t, rule.name)}
          {rule.built_in && <Badge tone="accent">{t('rules.builtIn')}</Badge>}
        </p>
        <p className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-mist-500">
          <span>{t('rules.when')}</span>
          {source ? (
            <span className="inline-flex items-center gap-1 rounded-md bg-ink-800 px-1.5 py-0.5 text-mist-300">
              <SourceMark kind={source.kind} protocol={source.protocol} src={source.icon_url} className="h-4 w-4 text-[7px]" />
              {source.name}
            </span>
          ) : (
            <span className="rounded-md bg-ink-800 px-1.5 py-0.5 text-mist-300">{t('rules.anySource')}</span>
          )}
          {rule.conditions.map((condition, i) => (
            <span key={i} className="rounded-md bg-ink-800 px-1.5 py-0.5 text-mist-300">
              {t(`rules.field.${condition.field}`)} {t(`rules.op.${condition.op}`)} <code className="font-mono break-all text-accent-400">{condition.value}</code>
            </span>
          ))}
        </p>
        <p className="mt-1.5 flex flex-wrap items-center gap-1.5 text-xs text-mist-500">
          <span>{t('rules.then')}</span>
          <ThenChips actions={rule.actions} />
        </p>
      </button>
      <div className="flex shrink-0 flex-col items-end gap-2">
        <Switch label={rule.name} checked={rule.enabled} onChange={onToggle} hideLabel />
        <div className="flex">
          <button type="button" disabled={index === 0} onClick={() => onMove(-1)} className="rounded-md p-1 text-mist-500 hover:text-mist-100 disabled:opacity-30" aria-label={t('rules.up')} title={t('rules.up')}>
            <Symbol name="up" className="h-3.5 w-3.5" />
          </button>
          <button type="button" disabled={last} onClick={() => onMove(1)} className="rounded-md p-1 text-mist-500 hover:text-mist-100 disabled:opacity-30" aria-label={t('rules.down')} title={t('rules.down')}>
            <Symbol name="chevronDown" className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    </li>
  )
}

function ThenChips({ actions }: { actions: RuleActions }) {
  const { t } = useTranslation()
  return (
    <>
      {actions.drop && <span className="rounded-md bg-bad-500/10 px-1.5 py-0.5 text-bad-500">{t('rules.drop')}</span>}
      {actions.priority && <span className={'rounded-md border px-1.5 py-px ' + PRIORITY_CHIP[actions.priority]}>{t(`priority.${actions.priority}`)}</span>}
      {actions.resolves && <span className="rounded-md bg-ok-500/10 px-1.5 py-0.5 text-ok-500">{t('rules.resolves')}</span>}
      {actions.group_key && (
        <span className="rounded-md bg-ink-800 px-1.5 py-0.5 text-mist-300">
          {t('rules.groupBy')} <code className="font-mono">{actions.group_key}</code>
        </span>
      )}
      {actions.title_template && (
        <span className="rounded-md bg-ink-800 px-1.5 py-0.5 text-mist-300">
          {t('rules.titleAs')} <code className="font-mono">{actions.title_template}</code>
        </span>
      )}
      {actions.icon && (
        <span className="inline-flex items-center gap-1 rounded-md bg-ink-800 px-1.5 py-0.5 text-mist-300">
          {iconPreview(actions.icon) && <img src={iconPreview(actions.icon) ?? undefined} alt="" className="h-3.5 w-3.5 object-contain" />}
          {t('icon.chip')}
        </span>
      )}
      {actions.push && (
        <span className="inline-flex items-center gap-1 rounded-md bg-accent-500/10 px-1.5 py-0.5 text-accent-400">
          <Symbol name="phone" className="h-3 w-3" />
          {t(`push.${actions.push}`)}
        </span>
      )}
    </>
  )
}

/** Type a message, see which rules hit and what comes out. The server decides, with the same code as for real. */
function Tester({ sources }: { sources: Source[] }) {
  const { t } = useTranslation()
  const [sourceId, setSourceId] = useState('')
  const [title, setTitle] = useState('Backup job FAILED on pve01')
  const [body, setBody] = useState('')
  const [result, setResult] = useState<{ matched: string[]; actions: RuleActions } | null>(null)

  useEffect(() => {
    const timer = window.setTimeout(() => {
      api
        .post<{ matched: string[]; actions: RuleActions }>('/api/rules/try', { source_id: sourceId ? Number(sourceId) : null, title, body })
        .then(setResult)
        .catch(() => setResult(null))
    }, 300)
    return () => window.clearTimeout(timer)
  }, [sourceId, title, body])

  return (
    <Section title={t('rules.tester.title')} intro={t('rules.tester.intro')} help={t('rules.tester.help')}>
      <SelectField label={t('rules.tester.source')} value={sourceId} onChange={setSourceId}>
        <option value="">{t('rules.tester.anySource')}</option>
        {sources.map((source) => (
          <option key={source.id} value={source.id}>
            {source.name}
          </option>
        ))}
      </SelectField>
      <Field label={t('rules.tester.messageTitle')} value={title} onChange={(event) => setTitle(event.target.value)} />
      <div className="flex flex-col gap-1.5">
        <label htmlFor="tester-body" className="text-sm font-medium text-mist-300">
          {t('rules.tester.body')}
        </label>
        <textarea id="tester-body" rows={3} value={body} onChange={(event) => setBody(event.target.value)} className={INPUT_CLASS + ' font-mono text-sm'} />
      </div>
      {result && (
        <div className="flex flex-col gap-2 rounded-xl border border-ink-700 bg-ink-950/60 p-3 text-sm" aria-live="polite">
          {result.matched.length === 0 ? (
            <p className="text-mist-500">{t('rules.tester.none')}</p>
          ) : (
            <>
              <p className="text-xs text-mist-500">{t('rules.tester.matched', { count: result.matched.length })}</p>
              <ul className="flex flex-col gap-1">
                {result.matched.map((name) => (
                  <li key={name} className="flex items-center gap-2 text-mist-200">
                    <Symbol name="check" className="h-3.5 w-3.5 text-ok-500" />
                    {ruleName(t, name)}
                  </li>
                ))}
              </ul>
            </>
          )}
          <div className="mt-1 flex flex-wrap items-center gap-1.5 border-t border-ink-700 pt-2 text-xs text-mist-500">
            {t('rules.tester.result')}
            {result.actions.drop ? (
              <span className="rounded-md bg-bad-500/10 px-1.5 py-0.5 text-bad-500">{t('rules.drop')}</span>
            ) : (
              <>
                {result.actions.priority ? (
                  <span className={'rounded-md border px-1.5 py-px ' + PRIORITY_CHIP[result.actions.priority]}>{t(`priority.${result.actions.priority}`)}</span>
                ) : (
                  <span className="text-mist-400">{t('rules.tester.senderPriority')}</span>
                )}
                {result.actions.push && (
                  <span className="inline-flex items-center gap-1 rounded-md bg-accent-500/10 px-1.5 py-0.5 text-accent-400">
                    <Symbol name="phone" className="h-3 w-3" />
                    {t(`push.${result.actions.push}`)}
                  </span>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </Section>
  )
}

function Defaults() {
  const { t } = useTranslation()
  const notify = useNotice()
  const settings = useLoad(() => api.get<Settings>('/api/settings'), [])
  const [draft, setDraft] = useState<Settings | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (settings.data) setDraft(settings.data)
  }, [settings.data])

  if (!draft) return null
  const changed = JSON.stringify(draft) !== JSON.stringify(settings.data)

  async function save() {
    if (!draft) return
    try {
      settings.set(await api.put<Settings>('/api/settings', { values: draft }))
      setError(null)
      notify({ text: t('common.saved') })
    } catch (caught) {
      setError(errorMessage(caught))
    }
  }

  const number = (key: keyof Settings) => ({
    value: String(draft[key]),
    inputMode: 'numeric' as const,
    onChange: (event: ChangeEvent<HTMLInputElement>) => setDraft({ ...draft, [key]: Number(event.target.value.replace(/\D/g, '') || 0) }),
  })

  return (
    <Section title={t('rules.defaults.title')} intro={t('rules.defaults.intro')} help={t('rules.defaults.help')}>
      <SelectField label={t('rules.defaults.push')} value={draft.push_mode} onChange={(value) => setDraft({ ...draft, push_mode: value as PushMode })} help={t('rules.defaults.pushHelp')}>
        {PUSH_MODES.map((value) => (
          <option key={value} value={value}>
            {t(`push.${value}`)}
          </option>
        ))}
      </SelectField>
      <p className="-mt-2 text-xs text-mist-500">{t(`push.hint.${draft.push_mode}`)}</p>
      <SelectField
        label={t('rules.defaults.pushLanguage')}
        value={draft.push_language}
        onChange={(value) => setDraft({ ...draft, push_language: value as Settings['push_language'] })}
        help={t('rules.defaults.pushLanguageHelp')}
      >
        {PUSH_LANGUAGES.map((code) => (
          <option key={code} value={code}>
            {LANGUAGES[code].name}
          </option>
        ))}
      </SelectField>
      <Switch
        label={t('rules.defaults.sourceIcons')}
        hint={t('rules.defaults.sourceIconsHint')}
        help={t('rules.defaults.sourceIconsHelp')}
        checked={draft.push_source_icons}
        onChange={(value) => setDraft({ ...draft, push_source_icons: value })}
      />
      <div className="grid grid-cols-2 gap-3">
        <Field label={t('rules.defaults.window')} help={t('rules.defaults.windowHelp')} {...number('bundle_minutes')} />
        <Field label={t('rules.defaults.throttle')} help={t('rules.defaults.throttleHelp')} {...number('throttle_per_minute')} />
      </div>
      <div className="flex flex-col gap-3 rounded-xl border border-ink-700 bg-ink-900 p-3">
        <Switch label={t('rules.storm.title')} hint={t('rules.storm.hint')} checked={draft.storm_enabled} onChange={(value) => setDraft({ ...draft, storm_enabled: value })} help={t('rules.storm.help')} />
        {draft.storm_enabled && (
          <p className="flex flex-wrap items-center gap-1.5 text-sm text-mist-300">
            {t('rules.storm.from')}
            <input {...number('storm_count')} aria-label={t('rules.storm.count')} className="w-14 rounded-lg border border-ink-700 bg-ink-950 px-2 py-1 text-center tabular-nums" />
            {t('rules.storm.within')}
            <input {...number('storm_minutes')} aria-label={t('rules.storm.minutes')} className="w-14 rounded-lg border border-ink-700 bg-ink-950 px-2 py-1 text-center tabular-nums" />
            {t('rules.storm.then')}
          </p>
        )}
      </div>
      {error && <Banner tone="bad">{error}</Banner>}
      <div className="flex justify-end">
        <Button onClick={() => void save()} disabled={!changed}>
          {t('common.save')}
        </Button>
      </div>
    </Section>
  )
}

function RuleEditor({ rule, sources, onSaved, onClose }: { rule: Draft; sources: Source[]; onSaved: () => void; onClose: () => void }) {
  const { t } = useTranslation()
  const [draft, setDraft] = useState<Draft>(rule)
  const [error, setError] = useState<string | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const setActions = (patch: Partial<RuleActions>) => setDraft({ ...draft, actions: { ...draft.actions, ...patch } })
  const setCondition = (index: number, patch: Partial<Condition>) => setDraft({ ...draft, conditions: draft.conditions.map((c, i) => (i === index ? { ...c, ...patch } : c)) })
  const [picking, setPicking] = useState(false)
  const ruleSource = sources.find((source) => source.id === draft.source_id)

  async function save() {
    const body = { name: draft.name, enabled: draft.enabled, source_id: draft.source_id, conditions: draft.conditions, actions: draft.actions }
    try {
      if (draft.id) await api.put(`/api/rules/${draft.id}`, body)
      else await api.post('/api/rules', body)
      onSaved()
    } catch (caught) {
      setError(errorMessage(caught))
    }
  }

  async function remove() {
    if (!draft.id) return
    try {
      await api.delete(`/api/rules/${draft.id}`)
      onSaved()
    } catch (caught) {
      setError(errorMessage(caught))
    }
  }

  if (picking) {
    return (
      <Dialog title={t('icon.pickTitle', { name: draft.name.trim() || t('rules.editor.new') })} onClose={onClose} wide>
        <IconPicker
          value={draft.actions.icon ?? ''}
          onPick={(icon) => {
            setActions({ icon })
            setPicking(false)
          }}
          onBack={() => setPicking(false)}
        />
      </Dialog>
    )
  }

  return (
    <Dialog title={draft.id ? t('rules.editor.edit') : t('rules.editor.new')} onClose={onClose} wide>
      <div className="flex flex-col gap-5">
        {draft.built_in && <Explainer>{t('rules.editor.builtInNote')}</Explainer>}
        <Field label={t('rules.editor.name')} value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} help={t('rules.editor.nameHelp')} />

        <fieldset className="flex flex-col gap-3">
          <legend className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-mist-200">
            {t('rules.when')}
            <Help label={t('rules.when')}>{t('rules.editor.whenHelp')}</Help>
          </legend>
          <SelectField label={t('rules.editor.source')} value={draft.source_id ? String(draft.source_id) : ''} onChange={(value) => setDraft({ ...draft, source_id: value ? Number(value) : null })} help={t('rules.editor.sourceHelp')}>
            <option value="">{t('rules.anySource')}</option>
            {sources.map((source) => (
              <option key={source.id} value={source.id}>
                {source.name}
              </option>
            ))}
          </SelectField>
          {draft.conditions.map((condition, index) => (
            <div key={index} className="grid grid-cols-[1fr_1fr] gap-2 sm:grid-cols-[1fr_1fr_2fr_auto] sm:items-end">
              <select aria-label={t('rules.editor.field')} value={condition.field} onChange={(event) => setCondition(index, { field: event.target.value as Condition['field'] })} className={INPUT_CLASS + ' text-sm'}>
                {(['any', 'title', 'body'] as const).map((field) => (
                  <option key={field} value={field}>
                    {t(`rules.field.${field}`)}
                  </option>
                ))}
              </select>
              <select aria-label={t('rules.editor.op')} value={condition.op} onChange={(event) => setCondition(index, { op: event.target.value as Condition['op'] })} className={INPUT_CLASS + ' text-sm'}>
                {(['word', 'contains', 'regex'] as const).map((op) => (
                  <option key={op} value={op}>
                    {t(`rules.op.${op}`)}
                  </option>
                ))}
              </select>
              <input aria-label={t('rules.editor.value')} value={condition.value} placeholder={t(`rules.editor.placeholder.${condition.op}`)} onChange={(event) => setCondition(index, { value: event.target.value })} className={INPUT_CLASS + ' col-span-2 font-mono text-sm sm:col-span-1'} />
              <button
                type="button"
                disabled={draft.conditions.length === 1}
                onClick={() => setDraft({ ...draft, conditions: draft.conditions.filter((_, i) => i !== index) })}
                className="rounded-full p-1.5 text-mist-500 hover:text-bad-500 disabled:opacity-30 sm:mb-2"
                aria-label={t('rules.editor.removeCondition')}
                title={t('rules.editor.removeCondition')}
              >
                <Symbol name="close" />
              </button>
            </div>
          ))}
          {draft.conditions.length < 10 && (
            <button type="button" onClick={() => setDraft({ ...draft, conditions: [...draft.conditions, { field: 'any', op: 'word', value: '' }] })} className="self-start text-xs font-medium text-accent-400 hover:text-accent-300">
              + {t('rules.editor.addCondition')}
            </button>
          )}
          <p className="text-xs text-mist-500">{t('rules.editor.wordHint')}</p>
        </fieldset>

        <fieldset className="flex flex-col gap-3">
          <legend className="mb-2 flex items-center gap-1.5 text-sm font-semibold text-mist-200">
            {t('rules.then')}
            <Help label={t('rules.then')}>{t('rules.editor.thenHelp')}</Help>
          </legend>
          <Switch label={t('rules.editor.drop')} hint={t('rules.editor.dropHint')} checked={!!draft.actions.drop} onChange={(drop) => setActions({ drop: drop || undefined })} />
          {!draft.actions.drop && (
            <div className="grid gap-3 sm:grid-cols-2">
              <SelectField label={t('rules.editor.priority')} value={draft.actions.priority ?? ''} onChange={(value) => setActions({ priority: (value || undefined) as Priority | undefined })} help={t('rules.editor.priorityHelp')}>
                <option value="">{t('rules.editor.keep')}</option>
                {PRIORITIES.map((priority) => (
                  <option key={priority} value={priority}>
                    {t(`priority.${priority}`)}
                  </option>
                ))}
              </SelectField>
              <SelectField label={t('rules.editor.push')} value={draft.actions.push ?? ''} onChange={(value) => setActions({ push: (value || undefined) as PushMode | undefined })} help={t('rules.editor.pushHelp')}>
                <option value="">{t('rules.editor.default')}</option>
                {PUSH_MODES.map((mode) => (
                  <option key={mode} value={mode}>
                    {t(`push.${mode}`)}
                  </option>
                ))}
              </SelectField>
              <Field label={t('rules.editor.groupKey')} help={t('rules.editor.groupKeyHelp')} value={draft.actions.group_key ?? ''} onChange={(event) => setActions({ group_key: event.target.value || undefined })} />
              <Field label={t('rules.editor.titleTemplate')} help={t('rules.editor.titleTemplateHelp')} value={draft.actions.title_template ?? ''} onChange={(event) => setActions({ title_template: event.target.value || undefined })} />
              <Field label={t('rules.editor.resolves')} help={t('rules.editor.resolvesHelp')} value={draft.actions.resolves ?? ''} onChange={(event) => setActions({ resolves: event.target.value || undefined })} />
              <div className="flex flex-col gap-3 sm:col-span-2">
                <IconField
                  value={draft.actions.icon ?? ''}
                  onChange={(icon) => setActions({ icon: icon || undefined })}
                  onBrowse={() => setPicking(true)}
                  preview={iconPreview(draft.actions.icon)}
                  kind={ruleSource?.kind}
                  protocol={ruleSource?.protocol}
                  label={t('icon.ruleLabel')}
                  help={t('icon.ruleHelp')}
                  none={t('icon.ruleNone')}
                />
              </div>
            </div>
          )}
        </fieldset>

        {error && <Banner tone="bad">{error}</Banner>}
        <div className="flex flex-wrap items-center justify-between gap-2">
          {draft.id ? (
            confirmDelete ? (
              <span className="flex items-center gap-2 text-sm text-mist-300">
                {t('rules.editor.confirmDelete')}
                <Button variant="danger" size="sm" onClick={() => void remove()}>
                  {t('rules.editor.delete')}
                </Button>
              </span>
            ) : (
              <Button variant="ghost" size="sm" onClick={() => setConfirmDelete(true)}>
                <Symbol name="trash" className="h-3.5 w-3.5" />
                {t('rules.editor.delete')}
              </Button>
            )
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button onClick={() => void save()} disabled={!draft.name.trim()}>
              {t('common.save')}
            </Button>
          </div>
        </div>
      </div>
    </Dialog>
  )
}
