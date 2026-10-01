import { allVersions, FILES, isEntry, latestVersion, unseen } from './whatsnew'

/**
 * Guard for "What's new". In Nexview fields were missing from an entry twice, and the window silently showed the
 * previous version's text. Here that shows before a release. That the version about to be released has a text is
 * checked by backend/tests/test_presets.py, which knows the version.
 */
describe('whats new entries', () => {
  const versions = Object.keys(FILES.en.entries)

  it('exist, and every one has all four fields and a way to each section', () => {
    expect(versions.length).toBeGreaterThan(0)
    for (const language of ['de', 'en']) {
      for (const [version, entry] of Object.entries(FILES[language].entries)) {
        expect(isEntry(entry), `${language} ${version}`).toBe(true)
      }
    }
  })

  it('say the same in both languages: same versions, same number of sections and small lines', () => {
    expect(Object.keys(FILES.de.entries).sort()).toEqual([...versions].sort())
    for (const version of versions) {
      const de = FILES.de.entries[version] as { sections: unknown[]; small: string[] }
      const en = FILES.en.entries[version] as { sections: unknown[]; small: string[] }
      expect(de.sections.length, version).toBe(en.sections.length)
      expect(de.small.length, version).toBe(en.small.length)
    }
  })

  it('name versions as three numbers', () => {
    for (const version of versions) expect(version).toMatch(/^\d+\.\d+\.\d+$/)
  })

  it('open only for a version the account has not seen, never backwards', () => {
    const newest = latestVersion()
    expect(unseen(null, newest)).toBe(true)
    expect(unseen(newest, newest)).toBe(false)
    expect(unseen('1.0.0', '1.1.0')).toBe(true)
    expect(unseen('1.10.0', '1.9.0')).toBe(false)
    expect(unseen('1.0.0', null)).toBe(false)
  })

  it('never show a text ahead of the running version', () => {
    expect(allVersions('0.0.1')).toEqual([])
    expect(latestVersion('0.0.1')).toBeNull()
  })

  it('drop an entry that lacks a field', () => {
    expect(isEntry({ lead: 'x', sections: [], smallTitle: 'y' })).toBe(false)
    expect(isEntry({ lead: 'x', sections: [], small: [] })).toBe(false)
    expect(isEntry({ sections: [], smallTitle: 'y', small: [] })).toBe(false)
    expect(isEntry({ lead: 'x', smallTitle: 'y', small: [] })).toBe(false)
    expect(isEntry({ lead: 'x', sections: [{ title: 't', body: 'b' }], smallTitle: 'y', small: [] })).toBe(false)
  })
})
