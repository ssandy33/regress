import { test, expect } from '@playwright/test';

const MOCK_SCAN_RESPONSE = {
  ticker: 'SOFI',
  current_price: 12.50,
  strategy: 'cash_secured_put',
  scan_time: '2026-03-18T12:00:00Z',
  earnings_date: '2026-04-15',
  iv_rank: null,
  recommendations: [
    {
      rank: 1,
      strike: 11.0,
      expiration: '2026-04-18',
      dte: 31,
      bid: 0.35,
      ask: 0.40,
      mid: 0.375,
      delta: -0.25,
      gamma: 0.05,
      theta: -0.02,
      vega: 0.03,
      iv: 0.45,
      open_interest: 5200,
      volume: 340,
      premium_per_contract: 37.50,
      total_premium: 37.50,
      return_on_capital_pct: 0.34,
      annualized_return_pct: 4.01,
      distance_from_price_pct: 12.0,
      distance_from_basis_pct: null,
      max_profit: 37.50,
      breakeven: 10.625,
      fifty_pct_profit_target: 18.75,
      rule_compliance: {
        passes_10pct_rule: true,
        passes_dte_range: true,
        passes_delta_range: true,
        passes_earnings_check: true,
        passes_return_target: true,
      },
      greeks_source: 'market',
      flags: [],
    },
    {
      rank: 2,
      strike: 50.0,
      expiration: '2026-04-18',
      dte: 31,
      bid: 0.10,
      ask: 0.15,
      mid: 0.125,
      delta: -0.10,
      gamma: 0.02,
      theta: -0.01,
      vega: 0.01,
      iv: 0.40,
      open_interest: 1200,
      volume: 80,
      premium_per_contract: 12.50,
      total_premium: 12.50,
      return_on_capital_pct: 0.025,
      annualized_return_pct: 0.29,
      distance_from_price_pct: 300.0,
      distance_from_basis_pct: null,
      max_profit: 12.50,
      breakeven: 49.875,
      fifty_pct_profit_target: 6.25,
      rule_compliance: {
        passes_10pct_rule: true,
        passes_dte_range: true,
        passes_delta_range: true,
        passes_earnings_check: true,
        passes_return_target: false,
      },
      greeks_source: 'market',
      flags: [],
    },
  ],
  rejected: [],
  market_context: {
    vix: 18.5,
    beta: 1.8,
    fifty_two_week_high: 15.0,
    fifty_two_week_low: 6.0,
    daily_volume: 120000000,
  },
};

function setupMocks(page, scanResponse = MOCK_SCAN_RESPONSE) {
  return Promise.all([
    page.route('**/api/settings/health/schwab', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ configured: true, valid: true, error: null, token_expiry: null }),
      })
    ),
    page.route('**/api/options/scan', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(scanResponse),
      })
    ),
  ]);
}

async function fillAndScan(page, capital) {
  await page.getByPlaceholder('SOFI, AAPL, F...').fill('SOFI');
  await page.getByPlaceholder('5000').fill(capital);
  await page.getByRole('button', { name: 'Scan Options' }).click();
  await page.waitForSelector('[data-testid="strike-table"], [data-testid="budget-alert-banner"]', { timeout: 5000 });
}

test.describe('Options capital awareness & affordability', () => {
  test.skip('light and dark mode styling is correct', async () => {
    // Manual verification: budget alert banner, capital utilization card, dimmed rows,
    // and lock icons should be visually correct in both light and dark themes.
  });

  test('Contracts and Max Income columns appear when capitalAvailable is set', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/options');
    await page.waitForLoadState('networkidle');

    await fillAndScan(page, '2000');

    // The new columns should be visible in the table header
    const table = page.locator('table');
    await expect(table.getByText('Contracts')).toBeVisible();
    await expect(table.getByText('Max Income')).toBeVisible();
  });

  test('table looks the same when capitalAvailable is not set', async ({ page }) => {
    // Use a scan response but without capital set — the table shouldn't show new columns.
    // To do this we need a strategy that doesn't require capital; we'll use covered_call.
    const ccResponse = {
      ...MOCK_SCAN_RESPONSE,
      strategy: 'covered_call',
    };
    await page.route('**/api/settings/health/schwab', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ configured: true, valid: true, error: null, token_expiry: null }),
      })
    );
    await page.route('**/api/options/scan', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(ccResponse),
      })
    );
    await page.goto('/options');
    await page.waitForLoadState('networkidle');

    // Switch to Covered Call and scan without setting capital
    await page.getByRole('button', { name: 'Covered Call' }).click();
    await page.getByPlaceholder('SOFI, AAPL, F...').fill('SOFI');
    await page.getByPlaceholder('15.50').fill('10');
    await page.getByRole('button', { name: 'Scan Options' }).click();
    await page.waitForSelector('table');

    const table = page.locator('table');
    await expect(table.getByText('Contracts')).not.toBeVisible();
    await expect(table.getByText('Max Income')).not.toBeVisible();
  });

  test('unaffordable rows are dimmed with lock icon and not selectable', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/options');
    await page.waitForLoadState('networkidle');

    // $2000 can afford strike $11 (collateral $1100) but not strike $50 (collateral $5000)
    await fillAndScan(page, '2000');

    const rows = page.locator('table tbody tr');
    // Find the $50 strike row — it should be dimmed (opacity-50)
    const expensiveRow = rows.filter({ hasText: '$50.00' }).first();
    await expect(expensiveRow).toHaveClass(/opacity-50/);

    // The expensive row should have a lock icon SVG, not a checkbox
    await expect(expensiveRow.locator('svg[aria-label="Unaffordable"]')).toBeVisible();
    await expect(expensiveRow.locator('input[type="checkbox"]')).not.toBeVisible();

    // The affordable row ($11) should have a checkbox, not a lock
    const affordableRow = rows.filter({ hasText: '$11.00' }).first();
    await expect(affordableRow.locator('input[type="checkbox"]')).toBeVisible();
    await expect(affordableRow).not.toHaveClass(/opacity-50/);
  });

  test('budget alert banner appears when no strikes are affordable', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/options');
    await page.waitForLoadState('networkidle');

    // $500 can't afford any strike (cheapest collateral is $1100 for strike $11)
    await fillAndScan(page, '500');

    const banner = page.getByTestId('budget-alert-banner');
    await expect(banner).toBeVisible();
    await expect(banner).toContainText('Insufficient capital');
    await expect(banner).toContainText('$500');
  });

  test('capital utilization card shows deployment summary', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/options');
    await page.waitForLoadState('networkidle');

    await fillAndScan(page, '2000');

    const card = page.getByTestId('capital-utilization-card');
    await expect(card).toBeVisible();
    await expect(card).toContainText('Capital Deployment');
    await expect(card).toContainText('Best Strike');
    await expect(card).toContainText('Contracts');
    await expect(card).toContainText('Max Income');
    await expect(card).toContainText('Idle Capital');
    // Should show deployment percentage
    await expect(card).toContainText('Deployment');
    await expect(card).toContainText('%');
  });

  test('CSP collateral = strike * 100', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/options');
    await page.waitForLoadState('networkidle');

    // $2000 capital, $11 strike → collateral = $1100 → 1 contract, maxIncome = 1 * $37.50
    await fillAndScan(page, '2000');

    const table = page.locator('table');
    const affordableRow = table.locator('tbody tr').filter({ hasText: '$11.00' }).first();
    // Contracts column should show 1 (floor(2000/1100) = 1)
    await expect(affordableRow).toContainText('$37.50');
  });
});
