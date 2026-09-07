import { defineConfig, devices } from '@playwright/test'

// Requires the local dev Postgres (`just dev-db`) and a seeded operator
// account (FIRST_ADMIN_USERNAME/PASSWORD in .env) — same prerequisites as
// `just dev-local`. Run with: npm run test:e2e (frontend/), after `just
// dev-db` if it isn't already running.
try {
  process.loadEnvFile('../.env')
} catch {
  // .env absent (e.g. CI providing real env vars directly) — fall through.
}

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  retries: 0,
  reporter: 'list',
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'retain-on-failure',
  },
  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
  webServer: [
    {
      // No --reload here (unlike `just dev-local`): uvicorn's --reload
      // watches the whole repo, and Playwright writing trace/screenshot
      // files under frontend/test-results/ during a run triggers a file
      // change, restarting the API mid-test and killing in-flight requests.
      command:
        'cd .. && uv run uvicorn services.portfolio.main:app --host 0.0.0.0 --port 8080',
      url: 'http://localhost:8080/health',
      reuseExistingServer: true,
      timeout: 30_000,
    },
    {
      command: 'npm run dev',
      url: 'http://localhost:5173',
      reuseExistingServer: true,
      timeout: 30_000,
    },
  ],
})
