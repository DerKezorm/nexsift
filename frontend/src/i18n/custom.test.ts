import { coverageOf, merge, missingFile, validate, type Texts } from './custom'

const english: Texts = {
  common: { back: 'Back', close: 'Close' },
  inbox: { muted: '{{name}} is muted for an hour.', span_one: 'One message', span_other: '{{count}} messages' },
}
const BUILT_IN = ['de', 'en']

function file(body: Record<string, unknown>, meta: Record<string, unknown> = { code: 'fr', name: 'Français', label: 'fr' }): string {
  return JSON.stringify({ _meta: meta, ...body })
}

describe('custom languages', () => {
  it('take a partial file and count what is missing', () => {
    const report = validate(file({ common: { back: 'Retour' } }), english, BUILT_IN)
    expect(report.errors).toEqual([])
    expect(report.language?.meta).toMatchObject({ code: 'fr', name: 'Français', label: 'FR' })
    expect(report.language?.texts).toEqual({ common: { back: 'Retour' } })
    expect(report.missing).toEqual(['common.close', 'inbox.muted', 'inbox.span_one', 'inbox.span_other'])
    expect(report.coverage).toBe(0.2)
  })

  it('leave out a text whose placeholders differ from English, and keep the rest', () => {
    const report = validate(file({ common: { back: 'Retour' }, inbox: { muted: '{{nom}} est muet.' } }), english, BUILT_IN)
    expect(report.errors).toEqual([])
    expect(report.rejected).toEqual([{ key: 'inbox.muted', reason: 'placeholders' }])
    expect(report.language?.texts).toEqual({ common: { back: 'Retour' } })
  })

  it('ignore unknown keys and never let __proto__ through', () => {
    const raw = '{"_meta":{"code":"fr","name":"Français","label":"FR"},"common":{"back":"Retour","typo":"x"},"__proto__":{"polluted":"yes"}}'
    const report = validate(raw, english, BUILT_IN)
    expect(report.unknown.sort()).toEqual(['__proto__.polluted', 'common.typo'])
    expect(report.language?.texts).toEqual({ common: { back: 'Retour' } })
    expect(({} as Record<string, unknown>).polluted).toBeUndefined()
  })

  it('refuse texts that are not text', () => {
    const report = validate(file({ common: { back: 42, close: '  ' } }), english, BUILT_IN)
    expect(report.rejected).toEqual([
      { key: 'common.back', reason: 'notText' },
      { key: 'common.close', reason: 'empty' },
    ])
    expect(report.errors).toEqual(['noTexts'])
  })

  it('accept plural forms English does not have, checked against the "other" form', () => {
    const polish = file({ inbox: { span_one: 'Jedna', span_few: '{{count}} wiadomości', span_many: '{{count}} wiadomości', span_other: '{{count}} wiadomości' } }, { code: 'pl', name: 'Polski', label: 'PL' })
    const report = validate(polish, english, BUILT_IN)
    expect(report.unknown).toEqual([])
    expect(report.rejected).toEqual([])
    const wrong = validate(file({ inbox: { span_few: 'kilka' } }, { code: 'pl', name: 'Polski', label: 'PL' }), english, BUILT_IN)
    expect(wrong.rejected).toEqual([{ key: 'inbox.span_few', reason: 'placeholders' }])
  })

  it('count a plural as covered when any of its forms is there', () => {
    // Japanese knows only "other".
    const report = validate(file({ inbox: { span_other: '{{count}} 件' } }, { code: 'ja', name: '日本語', label: 'JA' }), english, BUILT_IN)
    expect(report.missing).toEqual(['common.back', 'common.close', 'inbox.muted'])
  })

  it('refuse broken files as a whole', () => {
    expect(validate('{nope', english, BUILT_IN).errors).toEqual(['notJson'])
    expect(validate('[]', english, BUILT_IN).errors).toEqual(['notJson'])
    expect(validate('{"common":{"back":"x"}}', english, BUILT_IN).errors).toEqual(['noMeta'])
    expect(validate(file({ common: { back: 'x' } }, { code: 'de', name: 'Deutsch', label: 'DE' }), english, BUILT_IN).errors).toEqual(['builtInCode'])
    expect(validate(file({ common: { back: 'x' } }, { code: 'French', name: '', label: 'FRAN' }), english, BUILT_IN).errors).toEqual(['badCode', 'badName', 'badLabel'])
    expect(validate(file({ common: { back: 'x'.repeat(600 * 1024) } }), english, BUILT_IN).errors).toEqual(['tooLarge'])
  })

  it('accept region and script codes', () => {
    for (const code of ['pt-BR', 'sr-Latn', 'fil']) {
      expect(validate(file({ common: { back: 'x' } }, { code, name: 'x', label: 'X' }), english, BUILT_IN).errors).toEqual([])
    }
  })

  it('lay new texts over old ones when adding, and hand out only what is missing', () => {
    const merged = merge({ common: { back: 'Retour' } }, { common: { close: 'Fermer' } })
    expect(merged).toEqual({ common: { back: 'Retour', close: 'Fermer' } })
    const language = { meta: { code: 'fr', name: 'Français', label: 'FR' }, texts: merged, uploadedAt: 0 }
    expect(coverageOf(language, english)).toBe(0.4)
    const missing = JSON.parse(missingFile(language, english, '0.2.0'))
    expect(missing).toEqual({ _meta: { code: 'fr', name: 'Français', label: 'FR', madeFor: '0.2.0' }, inbox: english.inbox })
  })
})
