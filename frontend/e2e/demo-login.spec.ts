import { expect, test } from '@playwright/test'

/** Demo mode: one click on a demo user, or /login?as=<user>, signs in without a password. */
test('one-click and ?as= demo login', async ({ page, browser }) => {
  await page.goto('/login')
  await page.getByText('qhead@demo.local').click()
  await expect(page.getByRole('heading', { name: 'Quality dashboard' })).toBeVisible()
  await expect(page.getByText('Audit log')).toBeVisible()

  const other = await (await browser.newContext()).newPage()
  await other.goto('/login?as=owner.vmc02')
  await expect(other.getByRole('heading', { name: 'Quality dashboard' })).toBeVisible()
  await expect(other.getByText('Process Owner VMC-02 (demo)')).toBeVisible()
  await expect(other.getByText('Audit log')).toHaveCount(0)
})
