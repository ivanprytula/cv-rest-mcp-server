import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// Separate from vite.config.ts (not merged via mergeConfig) so `vitest`
// never needs Tailwind's Vite plugin to actually process CSS in jsdom —
// tests assert class names, not computed styles, so Tailwind only needs
// to not break the build. Reuses the same plugin list anyway for parity.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    globals: true,
    css: false,
    // Playwright owns e2e/ — its test.describe/fixture API isn't a Vitest
    // suite, so this excludes those specs from being collected here too.
    exclude: ['**/node_modules/**', 'e2e/**'],
  },
})
