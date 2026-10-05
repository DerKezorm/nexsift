/** An own picture address, as opposed to a logo of the collections (`dashboard-icons/<name>`, `selfhst/<name>`). */
export function isOwnIcon(icon: string | undefined | null): boolean {
  return Boolean(icon && /^https?:\/\//i.test(icon))
}

/** Where the picker's preview of a collection logo comes from (nexsift fetches it; the page never asks a CDN). */
export function iconPreview(icon: string | undefined | null): string | null {
  return icon && !isOwnIcon(icon) ? `/api/icons/${icon}.png` : null
}
