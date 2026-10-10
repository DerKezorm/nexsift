/**
 * Pflichttests 33 and 34 of the shared sign-in blueprint (copied once from bauplaene/oidc, then nexsift's file), in
 * the variant of an app with one account (blueprint 06): the operator links the own account; nobody else comes in.
 *
 * authentik is the stand-in of e2e/fake-authentik.mjs: the part of its API the button uses, and the OpenID Connect
 * provider of the application the button makes, over http on 8797 with a key made at its start, sending the browser
 * straight back with a code for whoever POST /next named. Never a real authentik, never the network. The page is the
 * operator `tester` of global-setup.ts.
 */
import { expect, test, type Page } from '@playwright/test'

const UI = { 'X-Requested-By': 'nexsift' }
const AUTHENTIK = 'http://127.0.0.1:8797'

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
  await page.goto('/settings?tab=signin')
  await expect(page.getByRole('heading', { name: 'Sign-in', exact: true })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'Sign-in providers' })).toBeVisible()
  await expect(page.getByRole('heading', { name: 'authentik in one step' })).toBeVisible()
  await expect(page.locator('#sign-in-providers')).toContainText('No provider yet.')
  // Without a linked provider the password cannot go.
  await expect(page.getByRole('switch', { name: 'Sign-in with a password' })).toBeDisabled()

  // By hand: the form as a dialog, fields in the blueprint's order.
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
  await card.getByRole('button', { name: 'Set up', exact: true }).click()
  const steps = page.getByTestId('authentik-steps')
  await expect(steps).toContainText('Connection to authentik')
  await expect(steps).toContainText('authentik cannot be reached at this address')
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

test('33: the operator links the account, then signs in through the provider button; a stranger does not', async ({ page, browser }) => {
  const problems = collectProblems(page)
  await removeEntries(page)
  const setup = await page.request.post('/api/oidc/authentik/setup', { data: { url: AUTHENTIK, token: process.env.E2E_AUTHENTIK_TOKEN }, headers: UI })
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
  await expect(question).toContainText('Another issuer is another provider. 1 accounts will have to link again afterwards.')
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
  await expect(stranger.getByTestId('sign-in-error')).toContainText('There is no account for you here.')
  await strange.close()
  await removeEntries(page)
  expect(problems).toEqual([])
})
