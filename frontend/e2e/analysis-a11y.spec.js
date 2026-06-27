import { test, expect } from '@playwright/test';

/**
 * /analysis sidebar accessibility — form-field labeling + page heading (#409).
 *
 * The sidebar's asset search, both date-range inputs, and the earnings-dates
 * checkbox shipped with no id/name; their labels had no htmlFor; and the page
 * had no <h1>. These assertions fail on the pre-fix markup and pass once the
 * id/name/htmlFor wiring and the page <h1> are added.
 *
 * The page defaults to linear mode (where the earnings checkbox renders) and a
 * fresh browser context starts with empty storage, so the default applies. The
 * FRED health endpoint is mocked as configured to suppress the setup wizard.
 */
test.describe('Analysis sidebar form-field a11y @smoke @e2e', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/settings/health/fred', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ configured: true, valid: true, error: null }),
      })
    );
    await page.goto('/analysis');
    await page.waitForLoadState('networkidle');
  });

  test('asset search input has an id and an associated label', async ({ page }) => {
    await expect(page.locator('#asset-search')).toHaveCount(1);
    await expect(page.locator('label[for="asset-search"]')).toHaveCount(1);
  });

  test('both date-range inputs have ids', async ({ page }) => {
    await expect(page.locator('#date-start')).toHaveCount(1);
    await expect(page.locator('#date-end')).toHaveCount(1);
  });

  test('earnings-dates checkbox has an id in linear mode', async ({ page }) => {
    await expect(page.locator('#show-earnings')).toHaveCount(1);
  });

  test('the page has exactly one <h1>', async ({ page }) => {
    await expect(page.locator('h1')).toHaveCount(1);
  });
});
