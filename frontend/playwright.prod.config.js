import { defineConfig } from '@playwright/test';

/**
 * Production-build Playwright config — regression guard for issue #229.
 *
 * The default config (`playwright.config.js`) runs against `npm run dev`, which
 * never statically prerenders pages. The v1.0.0 nonce-CSP outage (#229) only
 * reproduces on a *production* build, where routes are prerendered at build
 * time and their inline framework scripts are baked without a nonce.
 *
 * This config runs `next build && next start` so `e2e/*.prod.spec.js` exercises
 * real production rendering. It is a separate config (not a project in the
 * default one) because the two need different web servers and base URLs.
 *
 * Run: `npm run test:e2e:prod`.
 */
const PORT = 3100;

export default defineConfig({
  testDir: './e2e',
  // Only the production-build specs — the default config runs everything else.
  testMatch: /.*\.prod\.spec\.js/,
  timeout: 60000,
  use: {
    baseURL: `http://localhost:${PORT}`,
    headless: true,
  },
  webServer: {
    // A fresh production build, then serve it exactly as production does.
    command: `npm run build && npm run start -- --port ${PORT}`,
    port: PORT,
    reuseExistingServer: !process.env.CI,
    // `next build` is slow on a cold cache — allow generous startup time.
    timeout: 240000,
  },
  projects: [{ name: 'chromium', use: { browserName: 'chromium' } }],
});
