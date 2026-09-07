import { test, expect } from './fixtures'

test.describe('theme and palette persistence', () => {
  test('an explicit dark choice survives a full page reload with no flash', async ({ page }) => {
    const themeButton = page.getByRole('button', { name: /^Theme:/ })
    await expect(themeButton).toHaveText('Theme: System')

    await themeButton.click()
    await expect(themeButton).toHaveText('Theme: Light')
    await themeButton.click()
    await expect(themeButton).toHaveText('Theme: Dark')
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')

    await page.reload()

    // index.html's inline boot script must apply data-theme before React
    // mounts — check immediately after reload rather than waiting on a
    // React-rendered element, so a flash-of-wrong-theme regression would
    // be caught even if it self-corrects within a render.
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
    await expect(themeButton).toHaveText('Theme: Dark')
  })

  test('switching palette updates data-palette and survives reload', async ({ page }) => {
    await page.getByLabel('Accent color').selectOption('green')
    await expect(page.locator('html')).toHaveAttribute('data-palette', 'green')

    await page.reload()
    await expect(page.locator('html')).toHaveAttribute('data-palette', 'green')
    await expect(page.getByLabel('Accent color')).toHaveValue('green')
  })
})
