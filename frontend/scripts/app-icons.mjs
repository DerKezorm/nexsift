/* The icons for the home screen and for notifications, rendered once from the light version of the mark.
 *
 * Same shape as components/Logo.tsx and public/logo.svg; the source of every version is nexapps/icons-vergleich/neu.py.
 * Rendered with Playwright, which the end-to-end tests bring anyway:  node scripts/app-icons.mjs
 *
 * icon-192.png is also what every push carries (sw.js, and ntfy via services/icons.NEXSIFT_LOGO). The maskable icon
 * is cropped by Android, so the mark sits smaller on a full white square. The Apple touch icon is full bleed: iOS
 * rounds it itself. The badge is one colour: Android tints everything that is not transparent.
 */
import { chromium } from '@playwright/test'

const GRADIENT = `<defs><linearGradient id="g" gradientUnits="userSpaceOnUse" x1="10" y1="10" x2="54" y2="54">
  <stop offset="0" stop-color="#a1a1aa"/><stop offset=".5" stop-color="#52525b"/><stop offset="1" stop-color="#18181b"/>
</linearGradient></defs>`
const MARK = `<path d="M13.5 15.5h37L37 32.5v11L27 49.5V32.5Z" fill="none" stroke="url(#g)" stroke-width="4.4" stroke-linejoin="round"/>
  <circle cx="45" cy="47" r="3.8" fill="#27272a" stroke="#fff" stroke-width="1.8"/>`

const tile = (s) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="${s}" height="${s}">${GRADIENT}
  <rect x="2" y="2" width="60" height="60" rx="16" fill="#fff"/>
  <rect x="2.75" y="2.75" width="58.5" height="58.5" rx="15.3" fill="none" stroke="#71717a" stroke-opacity=".35" stroke-width="1.5"/>
  ${MARK}</svg>`
// The mark spans about 11 to 53 across and 13 to 53 down; its middle goes to the middle of the square.
const full = (s, m) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="${s}" height="${s}">${GRADIENT}
  <rect width="64" height="64" fill="#fff"/>
  <g transform="translate(32 32) scale(${m}) translate(-32 -33)">${MARK}</g></svg>`
const bleed = (s) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="2 2 60 60" width="${s}" height="${s}">${GRADIENT}
  <rect x="2" y="2" width="60" height="60" fill="#fff"/>${MARK}</svg>`
// White on clear: the funnel's outline and the dot, a little bolder so they hold at the size of a status bar.
const badge = (s) => `<svg xmlns="http://www.w3.org/2000/svg" viewBox="6 7 52 52" width="${s}" height="${s}">
  <path d="M13.5 15.5h37L37 32.5v11L27 49.5V32.5Z" fill="none" stroke="#fff" stroke-width="5" stroke-linejoin="round"/>
  <circle cx="45" cy="47" r="4.4" fill="#fff"/></svg>`

const PICTURES = [
  ['public/icon-192.png', tile(192), 192],
  ['public/icon-512.png', tile(512), 512],
  ['public/icon-maskable-512.png', full(512, 0.8), 512],
  ['public/apple-touch-icon.png', bleed(180), 180],
  ['public/badge-96.png', badge(96), 96],
]

const browser = await chromium.launch()
for (const [path, svg, size] of PICTURES) {
  const page = await browser.newPage({ viewport: { width: size, height: size } })
  await page.setContent(`<body style="margin:0;background:transparent">${svg}</body>`)
  await page.locator('svg').screenshot({ path, omitBackground: true })
  await page.close()
  console.log('written:', path)
}
await browser.close()
