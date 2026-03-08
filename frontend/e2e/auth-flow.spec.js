import { test, expect } from '@playwright/test';

/**
 * Auth flow e2e tests for Issue #26 acceptance criteria.
 *
 * These tests run against the dev server started by Playwright (npm run dev).
 * Auth behavior depends on whether NEXTAUTH_SECRET, GITHUB_ID, GITHUB_SECRET
 * are set in the environment when the dev server starts.
 *
 * Note: /api/* routes are proxied to the backend (localhost:8000). When running
 * without a backend, /api/auth/* calls may fail — tests account for this.
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
