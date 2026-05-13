import { test, expect } from '@playwright/test';

/**
 * E2E coverage for #179 — Options scanner pre-fills its inputs from URL
 * query params on mount. The hook reads `ticker`, `strategy`, `shares`, and
 * `cost_basis` once via `useSearchParams()`; invalid values fall back to the
 * existing defaults. No auto-scan: the user must still click "Scan Options".
 */

function setupMocks(page) {
  return Promise.all([
    page.route('**/api/settings/health/schwab', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ configured: true, valid: true, error: null, token_expiry: null }),
      })
    ),
    // Default: succeed but record that it was called. Specific tests override.
    page.route('**/api/options/scan', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ticker: 'F',
          current_price: 12.5,
          strategy: 'covered_call',
          scan_time: '2026-05-12T12:00:00Z',
          earnings_date: null,
          iv_rank: null,
          recommendations: [],
          rejected: [],
          market_context: {},
        }),
      })
    ),
  ]);
}

const tickerInput = (page) => page.getByPlaceholder('SOFI, AAPL, F...');
const cspButton = (page) => page.getByRole('button', { name: 'Cash-Secured Put' });
const ccButton = (page) => page.getByRole('button', { name: 'Covered Call' });

const ACTIVE_CLASS = /bg-blue-600/;

test.describe('Options scanner — URL pre-fill', () => {
  test('?ticker=F pre-fills the ticker input', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/options?ticker=F');
    await page.waitForLoadState('networkidle');

    await expect(tickerInput(page)).toHaveValue('F');
  });

  test('?ticker=f normalizes to uppercase', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/options?ticker=f');
    await page.waitForLoadState('networkidle');

    await expect(tickerInput(page)).toHaveValue('F');
  });

  test('?ticker=F&strategy=covered_call activates Covered Call', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/options?ticker=F&strategy=covered_call');
    await page.waitForLoadState('networkidle');

    await expect(tickerInput(page)).toHaveValue('F');
    await expect(ccButton(page)).toHaveClass(ACTIVE_CLASS);
    await expect(cspButton(page)).not.toHaveClass(ACTIVE_CLASS);
  });

  test('full URL params pre-fill ticker, strategy, shares, cost basis', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/options?ticker=F&strategy=covered_call&shares=100&cost_basis=17240');
    await page.waitForLoadState('networkidle');

    await expect(tickerInput(page)).toHaveValue('F');
    await expect(ccButton(page)).toHaveClass(ACTIVE_CLASS);

    // Cost Basis and Shares Held inputs only render under covered_call.
    const costBasisInput = page.locator('input[placeholder="15.50"]');
    await expect(costBasisInput).toHaveValue('17240');

    const sharesInput = page.getByTestId('scanner-shares-held-input');
    await expect(sharesInput).toHaveValue('100');
  });

  test('?strategy=garbage falls back to cash_secured_put', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/options?strategy=garbage');
    await page.waitForLoadState('networkidle');

    await expect(cspButton(page)).toHaveClass(ACTIVE_CLASS);
    await expect(ccButton(page)).not.toHaveClass(ACTIVE_CLASS);
  });

  test('?shares=abc keeps default 100', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/options?strategy=covered_call&shares=abc');
    await page.waitForLoadState('networkidle');

    const sharesInput = page.getByTestId('scanner-shares-held-input');
    await expect(sharesInput).toHaveValue('100');
  });

  test('?cost_basis=xyz keeps cost basis empty', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/options?strategy=covered_call&cost_basis=xyz');
    await page.waitForLoadState('networkidle');

    const costBasisInput = page.locator('input[placeholder="15.50"]');
    await expect(costBasisInput).toHaveValue('');
  });

  test('/options with no params uses defaults', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/options');
    await page.waitForLoadState('networkidle');

    await expect(tickerInput(page)).toHaveValue('');
    await expect(cspButton(page)).toHaveClass(ACTIVE_CLASS);
  });

  test('user can edit a pre-filled ticker freely', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/options?ticker=F');
    await page.waitForLoadState('networkidle');

    const input = tickerInput(page);
    await expect(input).toHaveValue('F');

    await input.fill('AAPL');
    await expect(input).toHaveValue('AAPL');
  });

  test('does not auto-scan on mount — scan endpoint untouched until click', async ({ page }) => {
    let scanCalled = false;
    await page.route('**/api/settings/health/schwab', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ configured: true, valid: true, error: null, token_expiry: null }),
      })
    );
    await page.route('**/api/options/scan', (route) => {
      scanCalled = true;
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          ticker: 'F',
          current_price: 12.5,
          strategy: 'covered_call',
          scan_time: '2026-05-12T12:00:00Z',
          earnings_date: null,
          iv_rank: null,
          recommendations: [],
          rejected: [],
          market_context: {},
        }),
      });
    });

    await page.goto('/options?ticker=F&strategy=covered_call&shares=100&cost_basis=17240');
    await page.waitForLoadState('networkidle');
    // Give any deferred effects a chance to run.
    await page.waitForTimeout(500);

    expect(scanCalled).toBe(false);
  });
});
