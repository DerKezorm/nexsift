/**
 * Contract tests 33 and 34 of the shared sign-in module (started from the shared copy, then nexsift's file), in
 * the variant of an app with one account: the operator links the own account; nobody else comes in.
 *
 * authentik is the stand-in of e2e/fake-authentik.mjs: the part of its API the button uses, and the OpenID Connect
 * provider of the application the button makes, over http on 8797 with a key made at its start, sending the browser
 * straight back with a code for whoever POST /next named. Never a real authentik, never the network. The page is the
 * operator `tester` of global-setup.ts.
 */
import { expect, test, type Page } from '@playwright/test'

const UI = { 'X-Requested-By': 'nexsift' }
const AUTHENTIK = 'http://127.0.0.1:8797'
// How the browser reaches nexsift in these tests (playwright.config.ts): the public address the card suggests.
const APP = 'http://127.0.0.1:8790'

type Entry = { id: number; slug: string; label: string; issuer: string; client_id: string; scopes: string; enabled: boolean; trusts_second_factor: boolean }

async function entries(page: Page): Promise<Entry[]> {
  return (await (await page.request.get('/api/oidc/admin/providers')).json()) as Entry[]
}

async function removeEntries(page: Page): Promise<void> {
  // The password first: without a provider it must be on anyway, and the server turns it back on by itself.
  await page.request.put('/api/settings', { data: { values: { password_login: true } }, headers: UI })
  for (const entry of await entries(page)) await page.request.delete(`/api/oidc/admin/providers/${entry.id}`, { headers: UI })
}

async function next(person: Record<string, string>): Promise<void> {
  await fetch(`${AUTHENTIK}/next`, { method: 'POST', body: JSON.stringify(person) })
}

function collectProblems(page: Page): string[] {
  const problems: string[] = []
  page.on('console', (message) => {
    if (message.type() === 'error' && !/status of 4(01|03|09|22)/.test(message.text())) problems.push(message.text())
  })
  page.on('pageerror', (error) => problems.push(error.message))
  return problems
}

test('34: add, edit and remove a provider with a question; the authentik card lists its steps', async ({ page }) => {
  const problems = collectProblems(page)
  await removeEntries(page)
  // A fresh app: no public address yet (clearing it asks nothing).
  await page.request.put('/api/settings', { data: { values: { public_url: '' } }, headers: UI })
  await page.goto('/settings?tab=signin')
  await expect(page.getByRole('heading', { name: 'Sign-in', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Sign-in providers' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'authentik in one step' })).toBeVisible()
  await expect(page.locator('#sign-in-providers')).toContainText('No provider yet.')
  // Without a linked provider the password cannot go.
  await expect(page.getByRole('switch', { name: 'Sign-in with a password' })).toBeDisabled()

  // By hand: the form as a dialog, fields in the shared order.
  await page.getByRole('button', { name: 'Add a provider' }).click()
  const form = page.getByTestId('provider-form')
  const order = ['Name on the button', 'Short name', 'Issuer', 'Client ID', 'Client secret', 'Redirect address for the provider', 'On', 'More']
  const tops: number[] = []
  for (const name of order) tops.push((await form.getByText(name, { exact: true }).first().boundingBox())!.y)
  expect(tops).toEqual([...tops].sort((a, b) => a - b))
  await expect(form.getByText('New people get an account')).toHaveCount(0)
  await form.getByLabel('Name on the button').fill('Stand-in')
  await expect(form.getByLabel('Short name')).toHaveValue('stand-in')
  await form.getByLabel('Issuer').fill(AUTHENTIK)
  await form.getByLabel('Client ID').fill('e2e-client')
  await form.getByLabel('Client secret').fill(`e2e-${Date.now()}`)
  await form.getByRole('button', { name: 'Save' }).click()
  const list = page.getByTestId('provider-list')
  const row = list.locator('li').filter({ hasText: 'Stand-in' })
  await expect(row).toContainText(AUTHENTIK)
  await expect(row).toContainText('on')
  await row.getByRole('button', { name: 'Edit' }).click()
  await expect(form.getByText('Short name: stand-in')).toBeVisible()
  await form.getByLabel('Name on the button').fill('Stand-in 2')
  await form.getByRole('button', { name: 'Save' }).click()
  const renamed = list.locator('li').filter({ hasText: 'Stand-in 2' })
  await expect(renamed).toBeVisible()
  await renamed.getByRole('button', { name: 'Remove' }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog).toContainText('accounts lose the link')
  await dialog.getByRole('button', { name: 'Remove' }).click()
  await expect(page.locator('#sign-in-providers')).toContainText('No provider yet.')

  // The button: an address nobody answers at gives the step list with the first step failed, in words.
  const card = page.locator('#sign-in-authentik')
  await card.getByLabel('Address of authentik', { exact: true }).fill('http://127.0.0.1:9')
  await card.getByLabel('API token', { exact: true }).fill(process.env.E2E_AUTHENTIK_TOKEN!)
  // Without a public address the card suggests the browser's own; the button takes it first (module 1.0.10).
  await expect(card.getByTestId('authentik-no-address')).toContainText(APP)
  await card.getByRole('button', { name: 'Use it and set up', exact: true }).click()
  const steps = page.getByTestId('authentik-steps')
  await expect(steps).toContainText('Connection to authentik')
  await expect(steps).toContainText('authentik cannot be reached at this address')
  // The address stayed saved although the run failed later: card 1 shows it, the suggestion is gone.
  await expect(card.getByTestId('authentik-no-address')).toHaveCount(0)
  await expect(page.getByRole('textbox', { name: 'Public address', exact: true })).toHaveValue(APP)
  // The stand-in: every step by its name, the seventh of an app with one account included, and the entry.
  await card.getByLabel('Address of authentik', { exact: true }).fill(AUTHENTIK)
  await card.getByLabel('API token', { exact: true }).fill(process.env.E2E_AUTHENTIK_TOKEN!)
  await card.getByRole('button', { name: 'Set up', exact: true }).click()
  for (const name of ['Connection to authentik', 'Signing key', 'Mappings for name and address', 'Provider', 'Application', 'Settings here', 'Only your account']) {
    await expect(steps.locator('li').filter({ hasText: name }).first()).toBeVisible()
  }
  await expect(steps.locator('li')).toHaveCount(7)
  await expect(steps).not.toContainText('cannot')
  const made = list.locator('li').filter({ hasText: 'authentik' })
  await expect(made).toContainText(`${AUTHENTIK}/application/o/nexsift`)
  await expect(made).toContainText('set up through authentik')
  await removeEntries(page)
  expect(problems).toEqual([])
})

test('40: the authentik card suggests the address, warns behind a proxy, asks before a change and reports a stale redirect', async ({ page }) => {
  const problems = collectProblems(page)
  await removeEntries(page)
  await page.request.put('/api/settings', { data: { values: { public_url: '' } }, headers: UI })
  // A proxy that ends TLS tells the server https while the browser is on http: the address of the request differs.
  await page.route('**/api/oidc/authentik/address', (route) => route.continue({ headers: { ...route.request().headers(), 'x-forwarded-proto': 'https' } }))
  await page.goto('/settings?tab=signin')
  const card = page.locator('#sign-in-authentik')
  const none = card.getByTestId('authentik-no-address')
  await expect(none).toContainText('No public address yet.')
  await expect(none).toContainText(APP)
  await expect(none).toContainText(`${APP}/api/oidc/authentik/callback`)
  await expect(card.getByTestId('authentik-proxy-warning')).toContainText('The server receives this request as https://127.0.0.1:8790.')
  // "Use it only" saves the suggestion and sets nothing up.
  await card.getByRole('button', { name: 'Use it only', exact: true }).click()
  await expect(none).toHaveCount(0)
  await expect(page.getByRole('textbox', { name: 'Public address', exact: true })).toHaveValue(APP)
  // Set up with the stand-in: the entry registers exactly that address.
  await card.getByLabel('Address of authentik', { exact: true }).fill(AUTHENTIK)
  await card.getByLabel('API token', { exact: true }).fill(process.env.E2E_AUTHENTIK_TOKEN!)
  await card.getByRole('button', { name: 'Set up', exact: true }).click()
  await expect(page.getByTestId('authentik-steps').locator('li')).toHaveCount(7)
  await expect(card.getByTestId('authentik-stale')).toHaveCount(0)
  // Another public address: authentik still knows the old redirect address, so the server asks first.
  const field = page.getByRole('textbox', { name: 'Public address', exact: true })
  await field.fill('http://localhost:8790')
  await page.locator('#sign-in').getByRole('button', { name: 'Save' }).click()
  const question = page.locator('#sign-in').getByTestId('address-change')
  await expect(question).toContainText(`authentik still knows the redirect address ${APP}/api/oidc/authentik/callback.`)
  await question.getByRole('button', { name: 'Cancel' }).click()
  await expect(question).toHaveCount(0)
  await expect(field).toHaveValue(APP)
  expect((await (await page.request.get('/api/settings')).json()).public_url).toBe(APP)
  await field.fill('http://localhost:8790')
  await page.locator('#sign-in').getByRole('button', { name: 'Save' }).click()
  await page.locator('#sign-in').getByTestId('address-change').getByRole('button', { name: 'Save' }).click()
  await expect(field).toHaveValue('http://localhost:8790')
  // Until the button ran again the card says what authentik still knows.
  await expect(card.getByTestId('authentik-stale')).toContainText(`authentik still knows the old redirect address ${APP}/api/oidc/authentik/callback.`)
  await card.getByLabel('Address of authentik', { exact: true }).fill(AUTHENTIK)
  await card.getByLabel('API token', { exact: true }).fill(process.env.E2E_AUTHENTIK_TOKEN!)
  await card.getByRole('button', { name: 'Set up', exact: true }).click()
  await expect(page.getByTestId('authentik-steps').locator('li')).toHaveCount(7)
  await expect(card.getByTestId('authentik-stale')).toHaveCount(0)
  // And back to the address the other tests use, this time under Settings, Addresses (the same setting, the same
  // question): asked again, stale until the button ran again.
  await page.goto('/settings?tab=addresses')
  const second = page.getByRole('textbox', { name: 'Public address', exact: true })
  await second.fill(APP)
  await page.getByRole('button', { name: 'Save' }).first().click()
  const again = page.getByTestId('address-change')
  await expect(again).toContainText('authentik still knows the redirect address http://localhost:8790/api/oidc/authentik/callback.')
  await again.getByRole('button', { name: 'Save' }).click()
  await expect(second).toHaveValue(APP)
  await expect(again).toHaveCount(0)
  await page.goto('/settings?tab=signin')
  await expect(card.getByTestId('authentik-stale')).toContainText('http://localhost:8790/api/oidc/authentik/callback')
  await card.getByLabel('Address of authentik', { exact: true }).fill(AUTHENTIK)
  await card.getByLabel('API token', { exact: true }).fill(process.env.E2E_AUTHENTIK_TOKEN!)
  await card.getByRole('button', { name: 'Set up', exact: true }).click()
  await expect(page.getByTestId('authentik-steps').locator('li')).toHaveCount(7)
  await expect(card.getByTestId('authentik-stale')).toHaveCount(0)
  // (Clearing asks nothing.)
  await page.request.put('/api/settings', { data: { values: { public_url: '' } }, headers: UI })
  await removeEntries(page)
  expect(problems).toEqual([])
})

test('41: "Use it only" asks while a provider entered by hand is on, and saves once confirmed', async ({ page }) => {
  const problems = collectProblems(page)
  await removeEntries(page)
  await page.request.put('/api/settings', { data: { values: { public_url: '' } }, headers: UI })
  const made = await page.request.post('/api/oidc/admin/providers', {
    data: { label: 'By hand', slug: 'by-hand', issuer: AUTHENTIK, client_id: 'e2e-client', client_secret: `e2e-${Date.now()}`, scopes: 'openid profile email', enabled: true },
    headers: UI,
  })
  expect(made.status(), await made.text()).toBe(201)
  // Behind a proxy that ends TLS the redirect address the provider knows (https, as the proxy says) is not the browser's.
  await page.route('**/api/oidc/authentik/address', (route) => route.continue({ headers: { ...route.request().headers(), 'x-forwarded-proto': 'https' } }))
  await page.goto('/settings?tab=signin')
  const card = page.locator('#sign-in-authentik')
  await expect(card.getByTestId('authentik-no-address')).toContainText(APP)
  await card.getByRole('button', { name: 'Use it only', exact: true }).click()
  // The redirect address of the provider by hand changes with the public address: the server asks, nothing saved.
  const question = card.getByTestId('address-change')
  await expect(question).toContainText('For 1 provider entered by hand, change the redirect address there yourself.')
  await expect(question).not.toContainText('authentik still knows')
  expect((await (await page.request.get('/api/settings')).json()).public_url).toBe('')
  await question.getByRole('button', { name: 'Cancel' }).click()
  await expect(question).toHaveCount(0)
  await card.getByRole('button', { name: 'Use it only', exact: true }).click()
  await card.getByTestId('address-change').getByRole('button', { name: 'Save' }).click()
  await expect(card.getByTestId('authentik-no-address')).toHaveCount(0)
  expect((await (await page.request.get('/api/settings')).json()).public_url).toBe(APP)
  await page.request.put('/api/settings', { data: { values: { public_url: '' } }, headers: UI })
  await removeEntries(page)
  expect(problems).toEqual([])
})

test('33: the operator links the account, then signs in through the provider button; a stranger does not', async ({ page, browser }) => {
  const problems = collectProblems(page)
  await removeEntries(page)
  const setup = await page.request.post('/api/oidc/authentik/setup', { data: { url: AUTHENTIK, token: process.env.E2E_AUTHENTIK_TOKEN, public_url: APP }, headers: UI })
  expect((await setup.json()).ok, await setup.text()).toBe(true)
  // A name on the button other than the short name: the pages must name the provider by it, never by the slug.
  const [entry] = await entries(page)
  const renamed = await page.request.put(`/api/oidc/admin/providers/${entry.id}`, { data: { ...entry, label: 'Company login', client_secret: '' }, headers: UI })
  expect(renamed.ok(), await renamed.text()).toBe(true)

  // Linking under Settings, Account, with the password once more.
  await next({ sub: 'owner-33', preferred_username: 'someone-else', email: 'owner@example.com' })
  await page.goto('/settings')
  const item = page.getByTestId('my-providers').locator('li').filter({ hasText: 'Company login' })
  await expect(item).toContainText('Not linked')
  await item.getByRole('button', { name: 'Link' }).click()
  await item.getByLabel('Your password').fill(process.env.E2E_OPERATOR_PASSWORD!)
  await item.getByRole('button', { name: 'Link' }).click()
  await expect(page).toHaveURL(/\/settings$/)
  await expect(page.getByText('Your account is now linked to Company login.')).toBeVisible()
  await expect(page.getByTestId('my-providers').locator('li').filter({ hasText: 'Company login' })).toContainText('Linked')

  // The password off: the sign-in page shows only the button, and it brings the operator in.
  await page.goto('/settings?tab=signin')
  const password = page.getByRole('switch', { name: 'Sign-in with a password' })
  await expect(password).toBeEnabled()
  await password.click()
  await expect(password).toHaveAttribute('aria-checked', 'false')
  const fresh = await browser.newContext({ storageState: { cookies: [], origins: [] } })
  const visitor = await fresh.newPage()
  const visitorProblems = collectProblems(visitor)
  await visitor.goto('/login')
  await expect(visitor.getByRole('button', { name: 'Sign in with Company login' })).toBeVisible()
  await expect(visitor.getByLabel('Password')).toHaveCount(0)
  await visitor.getByRole('button', { name: 'Sign in with Company login' }).click()
  await visitor.waitForURL((url) => !url.pathname.startsWith('/login') && !url.pathname.startsWith('/api/'))
  await expect(visitor).not.toHaveURL(/error=/)
  expect((await (await visitor.request.get('/api/auth/me')).json()).name).toBe('tester')
  expect(visitorProblems).toEqual([])
  await fresh.close()

  // The button against another authentik (another address, so another issuer) asks first, as the form does; "Cancel"
  // leaves the entry and the link as they are.
  await page.request.put('/api/settings', { data: { values: { password_login: true } }, headers: UI })
  await page.goto('/settings?tab=signin')
  const card = page.locator('#sign-in-authentik')
  await card.getByLabel('Address of authentik', { exact: true }).fill('http://localhost:8797')
  await card.getByLabel('API token', { exact: true }).fill(process.env.E2E_AUTHENTIK_TOKEN!)
  await card.getByRole('button', { name: 'Set up', exact: true }).click()
  const question = page.getByTestId('authentik-issuer-change')
  await expect(question).toContainText('Another issuer is another provider. 1 account will have to link again afterwards.')
  await question.getByRole('button', { name: 'Cancel' }).click()
  await expect(question).toHaveCount(0)
  const [kept] = await entries(page)
  expect(kept.issuer).toBe(`${AUTHENTIK}/application/o/nexsift`)
  expect((await (await page.request.get('/api/oidc/me')).json())[0].linked).toBe(true)

  // A stranger at authentik, with the operator's address: nothing; the sign-in page says why, in words.
  await next({ sub: 'stranger-33', email: 'owner@example.com', preferred_username: 'tester' })
  const strange = await browser.newContext({ storageState: { cookies: [], origins: [] } })
  const stranger = await strange.newPage()
  await stranger.goto('/login')
  await expect(stranger.getByRole('button', { name: 'Sign in', exact: true })).toBeVisible()
  await stranger.getByRole('button', { name: 'Sign in with Company login' }).click()
  await expect(stranger).toHaveURL(/\/login\?error=oidc_no_account/)
  await expect(stranger.getByTestId('sign-in-error')).toContainText('This identity is not linked here. Only the identity linked to the account of nexsift gets in.')
  await strange.close()
  await removeEntries(page)
  expect(problems).toEqual([])
})

for (const width of [375, 390]) {
  test(`phone ${width}: the sign-in settings and the account do not scroll sideways, the provider keeps its name`, async ({ page }) => {
    const problems = collectProblems(page)
    await page.setViewportSize({ width, height: 800 })
    await removeEntries(page)
    const setup = await page.request.post('/api/oidc/authentik/setup', { data: { url: AUTHENTIK, token: process.env.E2E_AUTHENTIK_TOKEN, public_url: APP }, headers: UI })
    expect((await setup.json()).ok, await setup.text()).toBe(true)
    const [entry] = await entries(page)
    await page.request.put(`/api/oidc/admin/providers/${entry.id}`, { data: { ...entry, label: 'Company login', client_secret: '' }, headers: UI })
    // Linked, so that the switch names the command that brings the password back.
    await next({ sub: `owner-phone-${width}`, preferred_username: 'someone-else', email: 'owner@example.com' })
    const started = await page.request.post(`/api/oidc/${entry.slug}/link`, { data: { password: process.env.E2E_OPERATOR_PASSWORD }, headers: UI })
    expect(started.ok(), await started.text()).toBe(true)
    await page.goto((await started.json()).url as string)
    await page.waitForURL(/\/settings/)

    const sideways = () => page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
    await page.goto('/settings?tab=signin')
    await expect(page.getByTestId('provider-list')).toBeVisible()
    await expect(page.getByText('docker exec -it nexsift python -m app.reset_password')).toBeVisible()
    expect(await sideways()).toBeLessThanOrEqual(0)
    // The name of the provider is read in full: it has a row of its own above the marks and the buttons.
    const row = page.getByTestId('provider-list').locator('li').first()
    const name = row.getByText('Company login', { exact: true })
    await expect(name).toBeVisible()
    expect(await name.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true)
    await page.goto('/settings')
    await expect(page.getByTestId('my-providers')).toBeVisible()
    expect(await sideways()).toBeLessThanOrEqual(0)
    await removeEntries(page)
    expect(problems).toEqual([])
  })
}
