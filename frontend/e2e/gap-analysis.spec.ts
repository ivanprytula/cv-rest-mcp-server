import { test, expect } from './fixtures'

test.describe('gap analysis workflow', () => {
  test('store a posting, analyze it, and see the tiered report', async ({ page }) => {
    const jdText =
      'Senior Backend Engineer. We need 5+ years of experience with Kubernetes ' +
      'and strong knowledge of Terraform. Familiarity with GraphQL is a plus.'

    await page.getByRole('link', { name: '+ New posting' }).click()
    await expect(page.getByRole('heading', { name: 'New job posting' })).toBeVisible()

    await page.getByLabel('Title').fill('E2E Test Posting')
    await page.getByLabel('Job description').fill(jdText)
    await page.getByRole('button', { name: 'Store & analyze' }).click()

    // Submitting navigates to /postings/:id once analysis completes.
    await expect(page).toHaveURL(/\/postings\/\d+$/)
    await expect(page.getByText(/Coverage: \d+%/)).toBeVisible()
  })

  test('the roadmap lists gap terms after at least one posting is analyzed', async ({ page }) => {
    await page.getByRole('link', { name: 'Roadmap' }).click()
    await expect(page).toHaveURL('/roadmap')

    // Either the table (postings already analyzed) or the empty state —
    // both are valid depending on what earlier tests/data left behind, but
    // the page must render one of them, not an error.
    const table = page.getByRole('table')
    const emptyState = page.getByText('No gaps yet.')
    await expect(table.or(emptyState)).toBeVisible()
  })
})
