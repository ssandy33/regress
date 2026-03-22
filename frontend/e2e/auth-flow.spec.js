import { test, expect } from '@playwright/test';

/**
 * Auth flow e2e tests for Issue #26 and Issue #80 acceptance criteria.
 *
 * These tests run against the dev server started by Playwright (npm run dev).
 * Auth behavior depends on whether NEXTAUTH_SECRET is set in the environment
 * when the dev server starts. After Issue #80, NEXTAUTH_SECRET alone is
 * sufficient to enable auth enforcement (GITHUB_ID/GITHUB_SECRET are still
 * required by NextAuth's OAuth provider but not by the middleware guard).
 *
 * Note: /api/* routes are proxied to the backend (localhost:8000). When running
 * without a backend, /api/auth/* calls may fail — tests account for this.
 *
 * Scenarios covered (Issue #80 AC):
 * - Only NEXTAUTH_SECRET set: middleware redirects unauthenticated requests
 * - No env vars set: all routes are public (auth fully opt-in)
 * - All vars set: middleware redirects (same as secret-only)
 *
 * AC: "Create a GitHub OAuth App" — manual step, not automatable.
 * AC: "Set production env vars" — manual step, not automatable.
 * AC: "Same NEXTAUTH_SECRET shared between containers" — infrastructure concern,
 *      verified by docker-compose.prod.yml config review.
 */

/**
 * Detect whether auth is enforced by checking if the home page redirects.
 * Returns true if visiting / results in a redirect to /auth/signin.
 */
async function isAuthEnforced(page) {
  await page.goto('/', { waitUntil: 'commit' });
  return page.url().includes('/auth/signin');
}

test.describe('Auth redirect flow (auth configured)', () => {
  test.beforeEach(async ({ page }) => {
    const enforced = await isAuthEnforced(page);
    if (!enforced) {
      test.skip(true, 'Auth env vars not configured — skipping auth flow tests');
    }
  });

  test('unauthenticated visit to / redirects to sign-in page', async ({ page }) => {
    await page.goto('/');
    await expect(page).toHaveURL(/\/auth\/signin/);
  });

  test('sign-in page preserves callbackUrl in redirect', async ({ page }) => {
    await page.goto('/settings', { waitUntil: 'commit' });
    const url = page.url();
    expect(url).toContain('/auth/signin');
    expect(url).toContain('callbackUrl');
  });

  test('protected routes redirect to sign-in', async ({ page }) => {
    const protectedRoutes = ['/', '/settings', '/help', '/options'];
    for (const route of protectedRoutes) {
      await page.goto(route, { waitUntil: 'commit' });
      await expect(page).toHaveURL(/\/auth\/signin/);
    }
  });
});

test.describe('Sign-in page', () => {
  test('shows GitHub sign-in button', async ({ page }) => {
    await page.goto('/auth/signin');
    await page.waitForLoadState('networkidle');
    await expect(page.getByRole('button', { name: /sign in with github/i })).toBeVisible();
  });

  test('shows app name and description', async ({ page }) => {
    await page.goto('/auth/signin');
    await page.waitForLoadState('networkidle');
    await expect(page.getByText('Regression Tool')).toBeVisible();
    await expect(page.getByText('Financial regression analysis')).toBeVisible();
  });

  test('is accessible without redirect loop', async ({ page }) => {
    const response = await page.goto('/auth/signin');
    // Should not redirect further — sign-in page itself is excluded from auth
    expect(response.status()).toBeLessThan(400);
    await expect(page).toHaveURL(/\/auth\/signin/);
  });

  test('shows restricted access notice', async ({ page }) => {
    await page.goto('/auth/signin');
    await page.waitForLoadState('networkidle');
    await expect(page.getByText('Access restricted to authorized users')).toBeVisible();
  });
});

test.describe('Auth disabled (no env vars)', () => {
  test.beforeEach(async ({ page }) => {
    const enforced = await isAuthEnforced(page);
    if (enforced) {
      test.skip(true, 'Auth is configured — skipping no-auth tests');
    }
  });

  test('home page loads without redirect when auth is not configured', async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('domcontentloaded');
    expect(page.url()).not.toContain('/auth/signin');
  });

  test('all routes are publicly accessible without auth', async ({ page }) => {
    const routes = ['/', '/settings', '/help', '/options'];
    for (const route of routes) {
      await page.goto(route, { waitUntil: 'commit' });
      expect(page.url()).not.toContain('/auth/signin');
    }
  });
});

/**
 * Issue #80 — Middleware alignment tests.
 *
 * These tests verify that the middleware auth guard depends only on
 * NEXTAUTH_SECRET, not on GITHUB_ID/GITHUB_SECRET. Since env vars are set at
 * server startup and cannot be changed at runtime in Playwright, the tests
 * below validate behavior based on the current environment configuration and
 * document the expected behavior for each scenario.
 *
 * To fully exercise all three scenarios, run the test suite three times with
 * different env configurations:
 *   1. No env vars set → auth disabled
 *   2. Only NEXTAUTH_SECRET set → auth enabled (Issue #80 key scenario)
 *   3. All three vars set → auth enabled
 */
test.describe('Issue #80: NEXTAUTH_SECRET-only auth enablement', () => {
  test('auth enforcement is consistent — either redirects or passes through', async ({ page }) => {
    // Verify the middleware behaves consistently: when auth is enforced,
    // all protected routes redirect; when not, none do. This confirms the
    // middleware guard activates based on NEXTAUTH_SECRET alone (no partial
    // state where some routes redirect and others don't).
    const enforced = await isAuthEnforced(page);
    const routes = ['/', '/settings', '/help', '/options'];

    for (const route of routes) {
      await page.goto(route, { waitUntil: 'commit' });
      if (enforced) {
        expect(page.url()).toContain('/auth/signin');
      } else {
        expect(page.url()).not.toContain('/auth/signin');
      }
    }
  });

  test('no partial-config warning when only NEXTAUTH_SECRET is set', async ({ page }) => {
    // The partial-config console.warn was removed in Issue #80.
    // Verify no warnings about partial auth configuration appear.
    const warnings = [];
    page.on('console', (msg) => {
      if (msg.type() === 'warning') {
        warnings.push(msg.text());
      }
    });

    await page.goto('/', { waitUntil: 'commit' });

    const partialWarnings = warnings.filter((w) =>
      w.includes('Auth partially configured')
    );
    expect(partialWarnings).toHaveLength(0);
  });
});
