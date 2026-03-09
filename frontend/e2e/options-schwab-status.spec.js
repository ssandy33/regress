import { test, expect } from '@playwright/test';

test.describe('Options page Schwab API status indicator', () => {
  test('shows not-connected banner when Schwab is not configured', async ({ page }) => {
    // Mock the Schwab health endpoint to return not configured
    await page.route('**/api/settings/health/schwab', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ configured: false, valid: false, error: null, token_expiry: null }),
      })
    );

    await page.goto('/options');
    await page.waitForLoadState('networkidle');

    // Status banner should be visible with not-connected message
    const banner = page.getByTestId('schwab-status-banner');
    await expect(banner).toBeVisible();
    await expect(banner).toContainText('Schwab API: Not Connected');
    await expect(banner).toHaveAttribute('role', 'alert');

    // Status dot should be red
    const dot = page.getByTestId('schwab-status-dot');
    await expect(dot).toHaveClass(/bg-red-500/);

    // Scan button should be disabled
    const scanBtn = page.getByRole('button', { name: 'Scan Options' });
    await expect(scanBtn).toBeDisabled();
  });

  test('shows connected banner when Schwab is configured and valid', async ({ page }) => {
    // Mock the Schwab health endpoint to return configured + valid
    await page.route('**/api/settings/health/schwab', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          configured: true,
          valid: true,
          error: null,
          token_expiry: {
            refresh_token_expires: '2026-04-01T00:00:00+00:00',
            hours_remaining: 500,
            warning: false,
            expired: false,
          },
        }),
      })
    );

    await page.goto('/options');
    await page.waitForLoadState('networkidle');

    // Status banner should show connected
    const banner = page.getByTestId('schwab-status-banner');
    await expect(banner).toBeVisible();
    await expect(banner).toContainText('Schwab API: Connected');
    await expect(banner).toHaveAttribute('role', 'status');

    // Status dot should be green
    const dot = page.getByTestId('schwab-status-dot');
    await expect(dot).toHaveClass(/bg-green-500/);

    // Scan button should be enabled (not disabled by Schwab status)
    const scanBtn = page.getByRole('button', { name: 'Scan Options' });
    await expect(scanBtn).toBeEnabled();
  });

  test('shows not-connected banner when configured but token is invalid', async ({ page }) => {
    await page.route('**/api/settings/health/schwab', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          configured: true,
          valid: false,
          error: 'Connection failed',
          token_expiry: null,
        }),
      })
    );

    await page.goto('/options');
    await page.waitForLoadState('networkidle');

    const banner = page.getByTestId('schwab-status-banner');
    await expect(banner).toBeVisible();
    await expect(banner).toContainText('Schwab API: Not Connected');

    const scanBtn = page.getByRole('button', { name: 'Scan Options' });
    await expect(scanBtn).toBeDisabled();
  });

  test('scan button tooltip explains why it is disabled', async ({ page }) => {
    await page.route('**/api/settings/health/schwab', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ configured: false, valid: false, error: null, token_expiry: null }),
      })
    );

    await page.goto('/options');
    await page.waitForLoadState('networkidle');

    const scanBtn = page.getByRole('button', { name: 'Scan Options' });
    await expect(scanBtn).toHaveAttribute('title', 'Schwab API is not configured. Visit Settings to connect.');
  });

  test('shows not-connected banner when API call fails', async ({ page }) => {
    // Mock network failure
    await page.route('**/api/settings/health/schwab', (route) =>
      route.abort('failed')
    );

    await page.goto('/options');
    await page.waitForLoadState('networkidle');

    const banner = page.getByTestId('schwab-status-banner');
    await expect(banner).toBeVisible();
    await expect(banner).toContainText('Schwab API: Not Connected');

    const scanBtn = page.getByRole('button', { name: 'Scan Options' });
    await expect(scanBtn).toBeDisabled();
  });

  test('does not leak internal error details in the banner', async ({ page }) => {
    await page.route('**/api/settings/health/schwab', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          configured: true,
          valid: false,
          error: 'HTTP 401',
          token_expiry: null,
        }),
      })
    );

    await page.goto('/options');
    await page.waitForLoadState('networkidle');

    const banner = page.getByTestId('schwab-status-banner');
    await expect(banner).toBeVisible();
    // Should not expose HTTP status codes or internal error details
    await expect(banner).not.toContainText('HTTP 401');
    await expect(banner).toContainText('Not Connected');
  });
});
