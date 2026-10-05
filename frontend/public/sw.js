// nexsift's service worker: shows push notifications and opens the right line when one is tapped.
// It caches nothing and has no fetch handler, so it never stands between the app and a new version.

self.addEventListener('install', () => self.skipWaiting())
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()))

self.addEventListener('push', (event) => {
  let data = {}
  try {
    data = event.data ? event.data.json() : {}
  } catch {
    data = { title: 'nexsift', body: event.data ? event.data.text() : '' }
  }
  const title = data.title || 'nexsift'
  const options = {
    body: data.body || '',
    // The source's logo when it has one (an address the browser loads itself), else nexsift's own.
    icon: data.icon || '/icon-192.png',
    badge: '/badge-96.png',
    data: { url: data.url || '/' },
    // One notification per line in the inbox: a follow-up replaces the first instead of stacking up.
    tag: data.tag || undefined,
    renotify: Boolean(data.tag),
    requireInteraction: data.priority === 'crit',
  }
  event.waitUntil(self.registration.showNotification(title, options))
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const url = new URL((event.notification.data && event.notification.data.url) || '/', self.location.origin).href
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(async (windows) => {
      for (const client of windows) {
        if (new URL(client.url).origin === self.location.origin && 'focus' in client) {
          await client.focus()
          if ('navigate' in client) return client.navigate(url)
          return undefined
        }
      }
      return self.clients.openWindow(url)
    }),
  )
})
