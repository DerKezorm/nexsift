/**
 * Before any test: the operator account, made through the first-start setup, and its session saved for every test
 * (`storageState`). The password is made up for the run (playwright.config.ts) and lives only in its environment.
 */
import { request, type FullConfig } from '@playwright/test'

export const OPERATOR = 'tester'

export default async function globalSetup(config: FullConfig): Promise<void> {
  const baseURL = config.projects[0].use.baseURL!
  const context = await request.newContext({ baseURL, extraHTTPHeaders: { 'X-Requested-By': 'nexsift' } })
  const made = await context.post('/api/setup', {
    data: { name: OPERATOR, password: process.env.E2E_OPERATOR_PASSWORD, email: '' },
  })
  if (!made.ok()) throw new Error(`setup failed: ${made.status()} ${await made.text()}`)
  await context.storageState({ path: process.env.NEXSIFT_E2E_STATE! })
  await context.dispose()
}
