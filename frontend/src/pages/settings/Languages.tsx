import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

import { Dialog } from '../../components/Dialog'
import { useNotice } from '../../components/Notice'
import { Symbol } from '../../components/Symbol'
import { Badge, Banner, Button, Section } from '../../components/ui'
import { BUILT_IN_LANGUAGES, changeLanguage, LANGUAGES, refreshCustomLanguage } from '../../i18n'
import { coverageOf, merge, missingFile, template, validate, type CustomLanguage, type Report } from '../../i18n/custom'
import { customLanguage, removeLanguage, saveLanguage, useCustomLanguages } from '../../i18n/customStore'
import english from '../../i18n/en.json'
import { APP_VERSION } from '../../lib/version'

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'application/json' }))
  const link = document.createElement('a')
  link.href = url
  link.download = name
  link.click()
  URL.revokeObjectURL(url)
}

function percent(share: number): string {
  // Never show 100 % for something that is not complete.
  return `${share < 1 ? Math.min(99, Math.floor(share * 100)) : 100} %`
}

/**
 * Settings, Languages: download the template, translate, upload. Every upload is checked first and the report
 * shown before anything is stored.
 */
export function Languages() {
  const { t, i18n } = useTranslation()
  const notify = useNotice()
  const custom = useCustomLanguages()
  const input = useRef<HTMLInputElement>(null)
  const [report, setReport] = useState<{ file: string; result: Report } | null>(null)
  const [removing, setRemoving] = useState<string | null>(null)

  async function pick(file: File | undefined) {
    if (!file) return
    const text = await file.text()
    setReport({ file: file.name, result: validate(text, english, BUILT_IN_LANGUAGES) })
    if (input.current) input.current.value = ''
  }

  async function remove(language: CustomLanguage) {
    removeLanguage(language.meta.code)
    setRemoving(null)
    await refreshCustomLanguage(language.meta.code)
    notify({ text: t('languages.removed', { name: language.meta.name }) })
  }

  return (
    <Section
      title={t('languages.title')}
      intro={t('languages.intro')}
      aside={
        <div className="flex flex-wrap gap-2">
          <Button variant="ghost" size="sm" onClick={() => download('nexsift-language-template.json', template(english, APP_VERSION))}>
            <Symbol name="download" className="h-3.5 w-3.5" />
            {t('languages.template')}
          </Button>
          <Button size="sm" onClick={() => input.current?.click()}>
            <Symbol name="upload" className="h-3.5 w-3.5" />
            {t('languages.upload')}
          </Button>
          <input ref={input} type="file" accept=".json,application/json" className="hidden" onChange={(event) => void pick(event.target.files?.[0])} />
        </div>
      }
    >
      <ol className="grid gap-2 text-sm text-mist-400 sm:grid-cols-3">
        {(['one', 'two', 'three'] as const).map((step, index) => (
          <li key={step} className="flex gap-2.5 rounded-xl border border-ink-700 bg-ink-900 p-3">
            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-ink-800 text-xs font-semibold text-mist-300">{index + 1}</span>
            <span>{t(`languages.step.${step}`, { example: '{{name}}' })}</span>
          </li>
        ))}
      </ol>

      <ul className="flex flex-col divide-y divide-ink-700 rounded-xl border border-ink-700">
        {BUILT_IN_LANGUAGES.map((code) => (
          <li key={code} className="flex items-center gap-3 px-3.5 py-2.5">
            <span className="w-8 font-mono text-xs text-mist-500">{LANGUAGES[code].label}</span>
            <span className="flex-1 text-sm text-mist-100">{LANGUAGES[code].name}</span>
            <Badge>{t('languages.builtIn')}</Badge>
          </li>
        ))}
        {custom.map((language) => {
          const share = coverageOf(language, english)
          const active = i18n.language === language.meta.code
          return (
            <li key={language.meta.code} className="flex flex-wrap items-center gap-x-3 gap-y-2 px-3.5 py-2.5">
              <span className="w-8 font-mono text-xs text-mist-500">{language.meta.label}</span>
              <div className="min-w-0 flex-1">
                <p className="flex items-center gap-2 text-sm text-mist-100">
                  {language.meta.name}
                  <span className="font-mono text-xs text-mist-600">{language.meta.code}</span>
                  {active && <Badge tone="accent">{t('languages.active')}</Badge>}
                </p>
                <p className="text-xs text-mist-500">
                  {[language.meta.author && t('languages.by', { author: language.meta.author }), language.meta.madeFor && t('languages.madeFor', { version: language.meta.madeFor })]
                    .filter(Boolean)
                    .join(' · ')}
                </p>
              </div>
              <div className="flex w-36 items-center gap-2" title={t('languages.coverageHint')}>
                <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-ink-700">
                  <span className={'block h-full rounded-full ' + (share < 1 ? 'bg-warn-500' : 'bg-ok-500')} style={{ width: `${Math.round(share * 100)}%` }} />
                </span>
                <span className="w-10 text-right text-xs text-mist-400 tabular-nums">{percent(share)}</span>
              </div>
              <div className="flex items-center gap-1">
                {!active && (
                  <Button variant="ghost" size="sm" onClick={() => void changeLanguage(language.meta.code)}>
                    {t('languages.use')}
                  </Button>
                )}
                {share < 1 && (
                  <IconButton symbol="download" label={t('languages.downloadMissing')} onClick={() => download(`nexsift-${language.meta.code}-missing.json`, missingFile(language, english, APP_VERSION))} />
                )}
                <IconButton
                  symbol="file"
                  label={t('languages.download')}
                  onClick={() => download(`nexsift-${language.meta.code}.json`, JSON.stringify({ _meta: language.meta, ...language.texts }, null, 2) + '\n')}
                />
                {removing === language.meta.code ? (
                  <Button variant="danger" size="sm" onClick={() => void remove(language)}>
                    {t('languages.confirmRemove')}
                  </Button>
                ) : (
                  <IconButton symbol="trash" label={t('languages.remove')} onClick={() => setRemoving(language.meta.code)} danger />
                )}
              </div>
            </li>
          )
        })}
      </ul>
      {custom.length === 0 && <p className="text-xs text-mist-500">{t('languages.none')}</p>}

      {report && <UploadReport file={report.file} report={report.result} onClose={() => setReport(null)} />}
    </Section>
  )
}

function IconButton({ symbol, label, onClick, danger = false }: { symbol: 'download' | 'file' | 'trash'; label: string; onClick: () => void; danger?: boolean }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      className={'rounded-full p-2 transition-colors ' + (danger ? 'text-mist-500 hover:bg-bad-500/10 hover:text-bad-500' : 'text-mist-500 hover:bg-ink-800 hover:text-mist-100')}
    >
      <Symbol name={symbol} className="h-3.5 w-3.5" />
    </button>
  )
}

function UploadReport({ file, report, onClose }: { file: string; report: Report; onClose: () => void }) {
  const { t } = useTranslation()
  const notify = useNotice()
  const language = report.language
  const existing = language ? customLanguage(language.meta.code) : undefined
  const [mode, setMode] = useState<'add' | 'replace'>('add')
  const [details, setDetails] = useState(false)
  // What the language will cover after saving: with "add", the old texts count too.
  const after = language ? coverageOf(existing && mode === 'add' ? { ...language, texts: merge(existing.texts, language.texts) } : language, english) : 0

  async function apply(use: boolean) {
    if (!language) return
    const saved = saveLanguage(language, existing ? mode : 'replace')
    await refreshCustomLanguage(saved.meta.code)
    if (use) await changeLanguage(saved.meta.code)
    notify({ text: t('languages.saved', { name: saved.meta.name }) })
    onClose()
  }

  return (
    <Dialog title={language ? t('languages.report.title', { name: language.meta.name }) : t('languages.report.failed')} onClose={onClose} wide>
      <div className="flex flex-col gap-4">
        <p className="font-mono text-xs text-mist-500">{file}</p>

        {report.errors.length > 0 ? (
          <Banner tone="bad">
            <ul className="flex flex-col gap-1">
              {report.errors.map((error) => (
                <li key={error}>{t(`languages.error.${error}`, { max: '512 KB' })}</li>
              ))}
            </ul>
          </Banner>
        ) : (
          <>
            <div className="flex items-center gap-3">
              <span className="h-2 flex-1 overflow-hidden rounded-full bg-ink-700">
                <span className={'block h-full rounded-full ' + (after < 1 ? 'bg-warn-500' : 'bg-ok-500')} style={{ width: `${Math.round(after * 100)}%` }} />
              </span>
              <span className="text-sm font-semibold text-mist-100 tabular-nums">{percent(after)}</span>
            </div>
            <ul className="flex flex-col gap-1.5 text-sm">
              <Line tone="ok" text={t('languages.report.covered', { percent: percent(report.coverage) })} />
              {report.missing.length > 0 && <Line tone="info" text={t('languages.report.missing', { count: report.missing.length })} />}
              {report.rejected.length > 0 && <Line tone="warn" text={t('languages.report.rejected', { count: report.rejected.length })} />}
              {report.unknown.length > 0 && <Line tone="info" text={t('languages.report.unknown', { count: report.unknown.length })} />}
            </ul>

            {(report.rejected.length > 0 || report.unknown.length > 0) && (
              <div>
                <button type="button" onClick={() => setDetails(!details)} aria-expanded={details} className="text-xs font-medium text-mist-400 hover:text-mist-100">
                  {details ? t('common.hide') : t('languages.report.details')}
                </button>
                {details && (
                  <ul className="ns-scroll mt-2 max-h-48 overflow-y-auto rounded-xl border border-ink-700 bg-ink-950/70 p-3 font-mono text-xs">
                    {report.rejected.map(({ key, reason }) => (
                      <li key={key} className="text-warn-500">
                        {key} <span className="text-mist-500">· {t(`languages.reason.${reason}`, { example: '{{count}}' })}</span>
                      </li>
                    ))}
                    {report.unknown.map((key) => (
                      <li key={key} className="text-mist-500">
                        {key} · {t('languages.reason.unknown')}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            )}

            {existing && (
              <fieldset className="flex flex-col gap-2 rounded-xl border border-ink-700 bg-ink-900 p-3">
                <legend className="px-1 text-xs font-medium text-mist-400">{t('languages.report.exists', { name: existing.meta.name })}</legend>
                {(['add', 'replace'] as const).map((value) => (
                  <label key={value} className="flex cursor-pointer items-start gap-2.5 text-sm">
                    <input type="radio" name="mode" checked={mode === value} onChange={() => setMode(value)} className="mt-1 accent-accent-500" />
                    <span>
                      <span className="block text-mist-100">{t(`languages.mode.${value}`)}</span>
                      <span className="block text-xs text-mist-500">{t(`languages.mode.${value}Hint`)}</span>
                    </span>
                  </label>
                ))}
              </fieldset>
            )}
          </>
        )}

        <div className="flex flex-wrap justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            {language ? t('common.cancel') : t('common.close')}
          </Button>
          {language && (
            <>
              <Button variant="ghost" onClick={() => void apply(false)}>
                {t('languages.report.save')}
              </Button>
              <Button onClick={() => void apply(true)}>{t('languages.report.saveAndUse')}</Button>
            </>
          )}
        </div>
      </div>
    </Dialog>
  )
}

function Line({ tone, text }: { tone: 'ok' | 'warn' | 'info'; text: string }) {
  const color = { ok: 'text-ok-500', warn: 'text-warn-500', info: 'text-mist-500' }[tone]
  return (
    <li className="flex items-start gap-2 text-mist-300">
      <Symbol name={tone === 'ok' ? 'check' : tone === 'warn' ? 'warn' : 'info'} className={'mt-0.5 h-4 w-4 shrink-0 ' + color} />
      {text}
    </li>
  )
}
