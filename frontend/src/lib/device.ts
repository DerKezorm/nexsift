/** A name for the device that says which one it is in the list of targets. */
export function deviceName(): string {
  const agent = navigator.userAgent
  const device = /iPhone/.test(agent) ? 'iPhone' : /iPad/.test(agent) ? 'iPad' : /Android/.test(agent) ? 'Android' : /Mac/.test(agent) ? 'Mac' : /Windows/.test(agent) ? 'Windows' : 'Browser'
  const browser = /Edg\//.test(agent) ? 'Edge' : /Firefox\//.test(agent) ? 'Firefox' : /Chrome\//.test(agent) ? 'Chrome' : /Safari\//.test(agent) ? 'Safari' : ''
  return browser && !(device === 'iPhone' || device === 'iPad') ? `${device} (${browser})` : device
}
