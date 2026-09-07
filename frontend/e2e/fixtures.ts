import { test as base, expect } from '@playwright/test'

// Logs in once per test via the real login form (not an API shortcut) so
// the auth flow itself stays covered, then hands the test an
// already-authenticated page.
export const test = base.extend({
  page: async ({ page }, use) => {
    const username = process.env.FIRST_ADMIN_USERNAME
    const password = process.env.FIRST_ADMIN_PASSWORD
    if (!username || !password) {
      throw new Error(
        'FIRST_ADMIN_USERNAME/FIRST_ADMIN_PASSWORD not set — export them or ensure ../.env has them.',
      )
    }

    await page.goto('/login')
    await page.getByLabel('Username').fill(username)
    await page.getByLabel('Password').fill(password)
    await page.getByRole('button', { name: 'Sign in' }).click()
    await expect(page.getByRole('link', { name: 'Postings' })).toBeVisible()

    await use(page)
  },
})

export { expect }
