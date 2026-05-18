import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './e2e',
  // `*.prod.spec.js` needs a production build — it runs under
  // `playwright.prod.config.js` (`npm run test:e2e:prod`), not `next dev`.
  testIgnore: /.*\.prod\.spec\.js/,
  timeout: 60000,
  use: {
    baseURL: 'http://localhost:3000',
    headless: true,
  },
  webServer: {
    command: 'npm run dev',
    port: 3000,
    reuseExistingServer: true,
    timeout: 60000,
  },
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
  ],
});
