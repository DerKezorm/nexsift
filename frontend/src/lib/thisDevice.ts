/**
 * Which Web Push target is the browser it runs in. The server hands out a short fingerprint of each device's push
 * address (sha256, first 16 hex digits); the browser computes the same from its own sign-up.
 */

async function ownSubscription(): Promise<PushSubscription | null> {
  if (!window.isSecureContext || !('serviceWorker' in navigator) || !('PushManager' in window)) return null
  const registration = await navigator.serviceWorker.getRegistration()
  return (await registration?.pushManager.getSubscription()) ?? null
}

export async function thisDevice(): Promise<string | null> {
  try {
    const subscription = await ownSubscription()
    if (!subscription) return null
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(subscription.endpoint))
    return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, '0'))
      .join('')
      .slice(0, 16)
  } catch {
    return null
  }
}

/** Takes the sign-up back in this browser too, after its target was removed on the server. */
export async function forgetThisDevice(): Promise<void> {
  try {
    await (await ownSubscription())?.unsubscribe()
  } catch {
    // Nothing to do: without a target the server sends nothing anyway.
  }
}
