import { test, expect } from '@playwright/test';

function setupMocks(page, { schwabConfigured = false } = {}) {
  return Promise.all([
    // Register specific routes BEFORE general /api/settings
    page.route('**/api/settings/schwab/auth-url', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ auth_url: 'https://api.schwabapi.com/v1/oauth/authorize?response_type=code&client_id=test-key', redirect_uri: 'https://127.0.0.1:8089/callback' }),
      })
    ),
    page.route('**/api/settings/schwab/callback', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'ok', access_token_expires: '2026-03-20T23:30:00+00:00', refresh_token_expires: '2026-03-27T00:00:00+00:00' }),
      })
    ),
    page.route(/\/api\/settings$/, (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            fred_api_key_set: true,
            cache_ttl_daily_hours: 24,
            cache_ttl_monthly_days: 30,
            default_date_range_years: 5,
            theme: 'system',
            schwab_configured: schwabConfigured,
            schwab_token_expires: schwabConfigured ? '2026-03-27T00:00:00+00:00' : null,
          }),
        });
      }
      return route.continue();
    }),
    page.route('**/api/settings/cache', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ entry_count: 0, total_size_bytes: 0, entries: [] }) })
    ),
    page.route('**/api/settings/health/fred', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ configured: true, valid: true }) })
    ),
    page.route('**/api/health/sources', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) })
    ),
    page.route('**/api/settings/backups', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ backups: [] }) })
    ),
    page.route('**/api/settings/cache/freshness', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ entries: [] }) })
    ),
  ]);
}

test.describe('Schwab OAuth Setup', () => {
  test('shows setup form when Schwab is not configured', async ({ page }) => {
    await setupMocks(page, { schwabConfigured: false });
    await page.goto('/settings');

    await expect(page.getByText('Not configured')).toBeVisible();
    await expect(page.getByPlaceholder('App Key (Client ID)')).toBeVisible();
    await expect(page.getByPlaceholder('App Secret (Client Secret)')).toBeVisible();
  });

  test('re-authorize button appears when configured', async ({ page }) => {
    await setupMocks(page, { schwabConfigured: true });
    await page.goto('/settings');

    await expect(page.getByText('Configured')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Re-authorize' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Test Connection' })).toBeVisible();
  });

  test('full setup flow: credentials to authorization link', async ({ page }) => {
    await setupMocks(page, { schwabConfigured: false });
    await page.goto('/settings');

    // Wait for form to stabilize after hydration
    const keyInput = page.getByPlaceholder('App Key (Client ID)');
    await expect(keyInput).toBeVisible();

    // Use click + keyboard.type to ensure React onChange fires
    await keyInput.click();
    await page.keyboard.type('test-key');
    await page.getByPlaceholder('App Secret (Client Secret)').click();
    await page.keyboard.type('test-secret');

    // Click Next within the Schwab API section
    const schwabSection = page.locator('section', { has: page.getByText('Schwab API') });
    await schwabSection.getByRole('button', { name: 'Next' }).click();

    // Step 2: authorization link appears
    await expect(page.getByRole('link', { name: 'Open Schwab Authorization' })).toBeVisible();

    // Step 3: paste callback URL and connect
    await page.getByPlaceholder('https://127.0.0.1:8089/callback?code=...').fill(
      'https://127.0.0.1:8089/callback?code=test-auth-code'
    );
    await page.getByRole('button', { name: 'Connect' }).click();

    // Success toast
    await expect(page.getByText('Schwab connected successfully!')).toBeVisible();
  });
});
