import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api } from '../api/client'
import type { About } from '../api/types'
import { useAuth } from '../auth'
import { useLoad } from '../lib/useLoad'
import { entryFor, latestVersion, unseen } from '../lib/whatsnew'
import { WhatsNewDialog } from './WhatsNewDialog'

/**
 * After an update, "What's new" once, as in nexbeat and nexcrate. The version seen is kept on the account, so the
 * window does not come back in another browser.
 *
 * ⚠️ The window closes at once and the note to the server follows. In nexdeck every way out waited for the answer,
 * and without a server the window could not be closed. If the note fails, the window comes back next time.
 */
export function WhatsNewAfterUpdate() {
  const { i18n } = useTranslation()
  const { account, setAccount } = useAuth()
  const about = useLoad(() => api.get<About>('/api/about'), [])
  const [closed, setClosed] = useState(false)
  const version = latestVersion(about.data?.version)
  const seen = typeof account?.prefs?.seen_version === 'string' ? account.prefs.seen_version : null
  if (closed || !account || !version || !unseen(seen, version)) return null
  const entry = entryFor(version, i18n.language)
  if (!entry) return null

  function close() {
    setClosed(true)
    if (!account) return
    const prefs = { ...account.prefs, seen_version: version }
    setAccount({ ...account, prefs })
    api.put('/api/me/prefs', { prefs }).catch(() => undefined)
  }

  return <WhatsNewDialog version={version} entry={entry} onClose={close} />
}
