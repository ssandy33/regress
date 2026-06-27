import { test, expect } from '@playwright/test';

/**
 * /options scanner accessibility — form-field labeling + heading order (#410).
 *
 * Every ChainFilters input shipped with no id/name, its labels had no htmlFor,
 * the page had no <h1>, and three <h3> section headers preceded the content
 * <h2> (broken order). These assertions fail on the pre-fix markup and pass
 * once id/name/htmlFor are wired, the section headers are demoted to <h2>, and
 * a single page <h1> is added before them in DOM order.
 *
 * CSP is the default strategy (its inputs render immediately); the Covered Call
 * inputs render only after toggling strategy, so they are checked separately.
 */
test.describe('Options scanner form-field a11y @smoke @e2e', () => {
  test.beforeEach(async ({ page }) => {
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

  test('always-visible + CSP inputs have ids', async ({ page }) => {
    for (const id of [
      '#scanner-ticker',
      '#scanner-capital',
      '#scanner-dte-min',
      '#scanner-dte-max',
      '#scanner-return-target',
      '#scanner-delta-min',
      '#scanner-delta-max',
      '#scanner-earnings-buffer',
    ]) {
      await expect(page.locator(id)).toHaveCount(1);
    }
  });

  test('Covered Call inputs have ids after toggling strategy', async ({ page }) => {
    await page.getByRole('button', { name: 'Covered Call' }).click();
    for (const id of ['#scanner-cost-basis', '#scanner-shares-held', '#scanner-call-distance']) {
      await expect(page.locator(id)).toHaveCount(1);
    }
  });

  test('every label[for] in the scanner resolves to an existing input', async ({ page }) => {
    const orphanLabels = await page.evaluate(() => {
      const labels = Array.from(document.querySelectorAll('aside label[for]'));
      return labels
        .map((l) => l.getAttribute('for'))
        .filter((id) => !document.getElementById(id));
    });
    expect(orphanLabels).toEqual([]);
  });

  test('the page has exactly one <h1> and it is the first heading in DOM order', async ({ page }) => {
    await expect(page.locator('h1')).toHaveCount(1);
    const firstHeadingTag = await page
      .locator('h1, h2, h3, h4, h5, h6')
      .first()
      .evaluate((el) => el.tagName);
    expect(firstHeadingTag).toBe('H1');
  });
});
