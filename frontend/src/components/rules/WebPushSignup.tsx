import { useState } from 'react'
import { useTranslation } from 'react-i18next'

import { api, ApiError, errorMessage } from '../../api/client'
import type { Settings } from '../../api/types'
import { useLoad } from '../../lib/useLoad'
import { Symbol } from '../Symbol'
import { Banner, Button } from '../ui'

export interface Subscription {
  url: string
  p256dh: string
  auth: string
}

/** The browser wants the server key as bytes; nexsift hands it out as base64url. */
function keyBytes(text: string): Uint8Array<ArrayBuffer> {
  const padded = (text + '='.repeat((4 - (text.length % 4)) % 4)).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(padded)
  const bytes = new Uint8Array(new ArrayBuffer(raw.length))
  for (let i = 0; i < raw.length; i += 1) bytes[i] = raw.charCodeAt(i)
  return bytes
}

function onIphone(): boolean {
  return /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)
}

function installed(): boolean {
  return window.matchMedia('(display-mode: standalone)').matches || (navigator as Navigator & { standalone?: boolean }).standalone === true
}

/**
 * Signs this very device up for Web Push. Everything that can stand in the way is said before the button: no https,
 * an iPhone outside the home screen app, a browser without push, the switch for the way out.
 */
export function WebPushSignup({ done, onSignedUp }: { done: Subscription | null; onSignedUp: (subscription: Subscription) => void }) {
  const { t } = useTranslation()
  const key = useLoad(() => api.get<{ enabled: boolean; key: string }>('/api/targets/webpush/key'), [])
  const settings = useLoad(() => api.get<Settings>('/api/settings'), [])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  if (!window.isSecureContext) {
    const publicUrl = settings.data?.public_url ?? ''
    return (
      <Banner tone="warn">
        {t('targets.webpush.needsHttps')}{' '}
        {publicUrl.startsWith('https://') && (
          <a href={`${publicUrl}/rules`} className="font-medium underline">
            {t('targets.webpush.openSecure', { url: publicUrl })}
          </a>
        )}
      </Banner>
    )
  }
  if (onIphone() && !installed()) return <Banner tone="info">{t('targets.webpush.iphone')}</Banner>
  if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
    return <Banner tone="bad">{t('targets.webpush.unsupported')}</Banner>
  }

  async function allow() {
    setError(null)
    try {
      await api.put('/api/settings', { values: { webpush_enabled: true } })
      await key.reload()
    } catch (caught) {
      setError(errorMessage(caught))
    }
  }

  async function signUp() {
    if (!key.data) return
    setBusy(true)
    setError(null)
    try {
      const permission = await Notification.requestPermission()
      if (permission !== 'granted') {
        setError(t('targets.webpush.denied'))
        return
      }
      await navigator.serviceWorker.register('/sw.js')
      const registration = await navigator.serviceWorker.ready
      const subscription =
        (await registration.pushManager.getSubscription()) ??
        (await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: keyBytes(key.data.key) }))
      const json = subscription.toJSON()
      if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) throw new Error(t('targets.webpush.incomplete'))
      onSignedUp({ url: json.endpoint, p256dh: json.keys.p256dh, auth: json.keys.auth })
    } catch (caught) {
      // The browser's own words (a DOMException) say more than any guess; nexsift's errors come translated.
      setError(caught instanceof Error && !(caught instanceof ApiError) ? t('targets.webpush.browserSaid', { message: caught.message }) : errorMessage(caught))
    } finally {
      setBusy(false)
    }
  }

  if (!key.data) return error ? <Banner tone="bad">{error}</Banner> : null

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-ink-700 bg-ink-900 p-3.5 text-sm text-mist-300">
      {!key.data.enabled ? (
        <>
          <p>{t('targets.webpush.wayOut')}</p>
          <div>
            <Button size="sm" onClick={() => void allow()}>
              {t('targets.webpush.allow')}
            </Button>
          </div>
        </>
      ) : done ? (
        <p className="flex items-center gap-2 text-ok-500">
          <Symbol name="check" className="h-4 w-4" />
          {t('targets.webpush.signedUp', { host: new URL(done.url).hostname })}
        </p>
      ) : (
        <>
          <p>{t('targets.webpush.ready')}</p>
          <div>
            <Button size="sm" loading={busy} onClick={() => void signUp()}>
              <Symbol name="phone" className="h-3.5 w-3.5" />
              {t('targets.webpush.signUp')}
            </Button>
          </div>
        </>
      )}
      {error && <Banner tone="bad">{error}</Banner>}
    </div>
  )
}
