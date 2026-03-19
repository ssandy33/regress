import { test, expect } from '@playwright/test';

test.describe('Options sidebar section grouping', () => {
  test.beforeEach(async ({ page }) => {
    // Mock endpoints so the page loads without real backends
    await page.route('**/api/settings/health/schwab', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ configured: true, valid: true, error: null, token_expiry: null }),
      })
    );

    await page.goto('/options');
    await page.waitForLoadState('networkidle');
  });

  test('displays three section headers', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'Asset' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Strategy' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Filters' })).toBeVisible();
  });

  test('all existing fields render in CSP mode', async ({ page }) => {
    // CSP is the default strategy
    await expect(page.getByPlaceholder('SOFI, AAPL, F...')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Cash-Secured Put' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Covered Call' })).toBeVisible();
    await expect(page.getByText('Capital Available ($)')).toBeVisible();
    await expect(page.getByText('DTE Range (days)')).toBeVisible();
    await expect(page.getByText('Monthly Return Target (%)')).toBeVisible();
    await expect(page.getByText('Delta Range')).toBeVisible();
    await expect(page.getByText('Earnings Buffer (days)')).toBeVisible();
  });

  test('all existing fields render in Covered Call mode', async ({ page }) => {
    await page.getByRole('button', { name: 'Covered Call' }).click();

    await expect(page.getByText('Cost Basis ($)')).toBeVisible();
    await expect(page.getByText('Shares Held')).toBeVisible();
    await expect(page.getByText('Min Call Distance % (10% Rule)')).toBeVisible();
    // Capital Available should not be visible in CC mode
    await expect(page.getByText('Capital Available ($)')).not.toBeVisible();
  });

  test('section headers remain visible after collapse and expand', async ({ page }) => {
    // Collapse sidebar
    await page.getByRole('button', { name: 'Collapse sidebar' }).click();
    // Section headers should be gone
    await expect(page.getByRole('heading', { name: 'Asset' })).not.toBeVisible();

    // Expand sidebar
    await page.getByRole('button', { name: 'Expand filters' }).click();
    // Section headers should be back
    await expect(page.getByRole('heading', { name: 'Asset' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Strategy' })).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Filters' })).toBeVisible();
  });
});
