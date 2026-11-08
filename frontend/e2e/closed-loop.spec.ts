import { readFileSync } from 'node:fs'

import { expect, test, type APIRequestContext, type Browser, type Page } from '@playwright/test'

/** Demo password comes from the environment or the repo's .env (never hard-coded). */
function demoPassword(): string {
  if (process.env.DEMO_USER_PASSWORD) return process.env.DEMO_USER_PASSWORD
  const env = readFileSync(new URL('../../.env', import.meta.url), 'utf8')
  const line = env.split('\n').find((l) => l.startsWith('DEMO_USER_PASSWORD='))
  if (!line) throw new Error('DEMO_USER_PASSWORD not set')
  return line.split('=', 2)[1].trim()
}

async function loginAs(browser: Browser, username: string): Promise<Page> {
  const context = await browser.newContext()
  const page = await context.newPage()
  await page.goto('/login')
  await page.getByLabel('Email').fill(`${username}@demo.local`)
  await page.getByLabel('Password').fill(demoPassword())
  await page.getByRole('button', { name: 'Sign in' }).click()
  await expect(page.getByRole('heading', { name: 'Quality dashboard' })).toBeVisible()
  return page
}

function notOkCsv(serial: string): Buffer {
  // SK-310 C-01 kingpin bore Ø30.000 +0.021/0 measured 30.025 -> Not OK (synthetic demo data)
  const rows = [
    'Dimension,Description,Nominal,+Tol,-Tol,Measured,Note',
    `C-01,Kingpin bore,30.000,0.021,0.000,30.025,e2e SN${serial} ${Date.now()}`,
    'C-02,Arm length,142.000,0.150,-0.150,142.010,e2e',
    'C-03,Mounting face flatness,0.000,0.050,0.000,0.012,e2e',
  ]
  return Buffer.from(rows.join('\n') + '\n')
}

/** Cancel leftover open SK-310 NCs from earlier runs so this run raises a fresh NC, not a recurrence. */
async function cleanup(request: APIRequestContext) {
  await request.post('/api/auth/login', { data: { email: 'qhead@demo.local', password: demoPassword() } })
  const page = await (await request.get('/api/ncs?bucket=open&limit=200')).json()
  for (const nc of page.items as { id: string; part_no: string; machine_code: string }[]) {
    if (nc.part_no === 'SK-310' && nc.machine_code === 'HMC-01') {
      await request.post(`/api/ncs/${nc.id}/cancel`, { data: { reason: 'e2e cleanup of an earlier test run' } })
    }
  }
}

test('Not OK upload -> live alert to owner -> corrective action -> verified and closed', async ({ browser, request }) => {
  await cleanup(request)
  const owner = await loginAs(browser, 'owner.hmc01')
  await expect(owner.getByLabel('live')).toBeVisible()

  // 1. Inspector uploads a Not OK report.
  const inspector = await loginAs(browser, 'inspector')
  await inspector.getByRole('link', { name: 'Reports' }).click()
  await inspector.getByLabel('Machine (if not in the file)').selectOption({ label: 'HMC-01' })
  const serial = String(9000 + Math.floor(Math.random() * 999))
  await inspector.locator('input[type=file]').setInputFiles({ name: `SK310_SN${serial}.csv`, mimeType: 'text/csv', buffer: notOkCsv(serial) })
  await expect(inspector.getByText(/Raised NC-\d{4}-\d{5}/)).toBeVisible()

  // 2. Owner sees the toast within seconds (SSE), opens the NC.
  const toast = owner.getByRole('status').filter({ hasText: '[NOT OK] SK-310' })
  await expect(toast).toBeVisible({ timeout: 5_000 })
  await toast.getByRole('link', { name: 'Open' }).click()
  await expect(owner.getByText('Open', { exact: true }).first()).toBeVisible()

  // 3. Acknowledge, record actions, add evidence, submit.
  await owner.getByRole('button', { name: 'Acknowledge' }).click()
  await expect(owner.getByText('Acknowledged', { exact: true }).first()).toBeVisible()
  await owner.getByLabel('Containment: what was done with suspect parts').fill('Quarantined last 6 parts from HMC-01 (e2e)')
  await owner.getByLabel('Root cause (6M)').selectOption('MACHINE')
  await owner.getByLabel('Root cause description').fill('Boring bar wear (e2e)')
  await owner.getByLabel('Corrective action').fill('Replace boring bar; shorten tool life (e2e)')
  await owner.getByLabel('Target date').fill('2026-12-31')
  await owner.getByRole('button', { name: 'Save actions' }).click()
  await expect(owner.getByText('In progress', { exact: true }).first()).toBeVisible()
  await owner.locator('input[type=file]').setInputFiles({ name: 'remeasure.csv', mimeType: 'text/csv', buffer: Buffer.from('C-01,30.010,re-measured (e2e)\n') })
  await expect(owner.getByRole('link', { name: 'remeasure.csv' })).toBeVisible()
  await owner.getByRole('button', { name: 'Submit for verification' }).click()
  await expect(owner.getByText('Pending verification', { exact: true }).first()).toBeVisible()
  const ncUrl = owner.url()

  // 4. Quality Head verifies -> Closed; timeline shows the measured alert time.
  const qhead = await loginAs(browser, 'qhead')
  await qhead.goto(ncUrl)
  await qhead.getByRole('button', { name: 'Verify and close' }).click()
  await expect(qhead.getByText('Closed', { exact: true }).first()).toBeVisible()
  await expect(qhead.getByText(/ms after file arrived/).first()).toBeVisible()
})
