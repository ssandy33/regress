import { test, expect } from '@playwright/test';

/**
 * Settings page accessibility — form-field labeling (issue #408).
 *
 * The General tab's "Default Date Range" <select> and the FRED API Key
 * <input type="password"> shipped with no id/name, and the Default Date Range
 * <label> had no htmlFor — so screen readers could not announce the select and
 * password managers could not target the key field.
 *
 * These assertions fail on the pre-fix markup (the ids/htmlFor did not exist)
 * and pass once id/name/htmlFor are wired. Only the generic settings endpoint
 * needs mocking; the remaining load calls fail gracefully and the General tab
 * (which holds both controls) renders regardless.
 */
function settingsResponse() {
  return {
    fred_api_key_set: false,
    cache_ttl_daily_hours: 24,
    cache_ttl_monthly_days: 30,
    default_date_range_years: 5,
    theme: 'system',
    schwab_configured: false,
    schwab_token_expires: null,
    okr_target_yield: null,
  };
}

test.describe('Settings page form-field a11y @smoke @e2e', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/settings', (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(settingsResponse()),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'ok' }),
      });
    });
    await page.goto('/settings');
    // General tab is the default; assert it is active before checking controls.
    await expect(page.getByTestId('settings-tab-general')).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });

  test('FRED API key input has id and name', async ({ page }) => {
    const input = page.locator('#fred-api-key');
    await expect(input).toHaveCount(1);
    await expect(input).toHaveAttribute('name', 'fred-api-key');
    await expect(input).toHaveAttribute('type', 'password');
  });

  test('Default Date Range label is associated with its select', async ({ page }) => {
    await expect(page.locator('label[for="default-date-range"]')).toHaveCount(1);
    const select = page.locator('#default-date-range');
    await expect(select).toHaveCount(1);
    await expect(select).toHaveAttribute('name', 'default-date-range');
  });
});
