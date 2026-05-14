import { test, expect } from '@playwright/test';

/**
 * E2E coverage for #190 — Options Scanner education layer (Phase A).
 *
 * Covers the four affordances locked in
 * `frontend/design-specs/scanner-education-v0.5.7.md`:
 *   1. Strategy primer (top-of-page, collapsed-by-default, localStorage-persisted)
 *   2. Column header tooltips (dedicated ⓘ icon, opens on click, closes on Escape)
 *   3. Per-row expansion ("What this trade commits you to" panel)
 *   4. Humanized rejected strikes (bulleted human sentences, neutral slate)
 */

const SCAN_PAYLOAD = {
  ticker: 'F',
  current_price: 13.67,
  strategy: 'covered_call',
  scan_time: '2026-05-13T12:00:00Z',
  earnings_date: null,
  iv_rank: null,
  recommendations: [
    {
      rank: 1,
      strike: 15.0,
      expiration: '2026-06-18',
      dte: 36,
      bid: 0.3,
      ask: 0.33,
      delta: 0.28,
      gamma: 0.05,
      theta: -0.012,
      vega: 0.08,
      iv: 0.34,
      open_interest: 23861,
      total_premium: 32.0,
      premium_per_contract: 32.0,
      return_on_capital_pct: 2.42,
      annualized_return_pct: 24.6,
      distance_from_price_pct: 9.7,
      distance_from_basis_pct: 13.5,
      breakeven: 12.89,
      fifty_pct_profit_target: 16.0,
      max_profit: 32.0,
      contracts: 1,
      rule_compliance: {
        passes_10pct_rule: true,
        passes_dte_range: true,
        passes_delta_range: true,
        passes_earnings_check: true,
        passes_return_target: true,
      },
      flags: [],
    },
    {
      rank: 2,
      strike: 16.0,
      expiration: '2026-06-18',
      dte: 36,
      bid: 0.16,
      ask: 0.19,
      delta: 0.17,
      gamma: 0.04,
      theta: -0.008,
      vega: 0.07,
      iv: 0.32,
      open_interest: 11692,
      total_premium: 18.0,
      premium_per_contract: 18.0,
      return_on_capital_pct: 1.36,
      annualized_return_pct: 13.8,
      distance_from_price_pct: 17.0,
      distance_from_basis_pct: 21.1,
      breakeven: 13.03,
      fifty_pct_profit_target: 9.0,
      max_profit: 18.0,
      contracts: 1,
      rule_compliance: {
        passes_10pct_rule: true,
        passes_dte_range: true,
        passes_delta_range: true,
        passes_earnings_check: true,
        passes_return_target: true,
      },
      flags: [],
    },
  ],
  rejected: [
    {
      strike: 12.5,
      expiration: '2026-06-18',
      rejection_reasons: ['fails_10pct_rule: strike -5.4% above basis, requires 10.0%'],
      human_reasons: [
        'Strike sits -5.4% above your $13.21 basis, but the 10.0% rule requires at least that much room.',
      ],
    },
    {
      strike: 16.0,
      expiration: '2026-07-16',
      rejection_reasons: [
        'delta_out_of_range: |0.42| not in [0.15, 0.35]',
        'low_open_interest: 12 < 50',
      ],
      human_reasons: [
        'Delta +0.42 is outside your 0.15–0.35 range — too close to the money, higher chance of assignment than you have set as acceptable.',
        'Only 12 contracts open — too thin to trade comfortably (the scanner requires at least 50).',
      ],
    },
  ],
  market_context: {},
};

function setupMocks(page) {
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
        body: JSON.stringify(SCAN_PAYLOAD),
      })
    ),
  ]);
}

// Clear localStorage once at the start of each test so primer state is
// deterministic. NOTE: don't use `context.addInitScript` — that would re-run
// on every navigation (including `page.reload()`) and wipe state mid-test,
// which defeats the persistence-across-reload assertion below.
async function clearScannerStorage(page) {
  await page.goto('/options');
  await page.evaluate(() => {
    try {
      window.localStorage.removeItem('scanner-primer-collapsed-cc');
      window.localStorage.removeItem('scanner-primer-collapsed-csp');
    } catch {
      // ignore
    }
  });
}

test.describe('Scanner education — strategy primer', () => {
  test('renders collapsed by default and toggles on click', async ({ page }) => {
    await setupMocks(page);
    await clearScannerStorage(page);
    await page.goto('/options?ticker=F&strategy=covered_call&shares=100&cost_basis=13.2066');
    await page.waitForLoadState('networkidle');

    const primer = page.getByTestId('scanner-strategy-primer');
    await expect(primer).toBeVisible();

    // Body should be hidden initially.
    await expect(page.getByTestId('scanner-strategy-primer-body')).toHaveCount(0);

    // Click the toggle — body appears with the covered-call copy.
    await page.getByTestId('scanner-strategy-primer-toggle').click();
    const body = page.getByTestId('scanner-strategy-primer-body');
    await expect(body).toBeVisible();
    await expect(body).toContainText('You own 100+ shares');
  });

  test('persists expanded state across reload (per strategy)', async ({ page }) => {
    await setupMocks(page);
    await clearScannerStorage(page);
    await page.goto('/options?ticker=F&strategy=covered_call');
    await page.waitForLoadState('networkidle');

    await page.getByTestId('scanner-strategy-primer-toggle').click();
    await expect(page.getByTestId('scanner-strategy-primer-body')).toBeVisible();

    // Reload — expanded state persists for CC.
    await page.reload();
    await page.waitForLoadState('networkidle');
    await expect(page.getByTestId('scanner-strategy-primer-body')).toBeVisible();
  });

  test('CC and CSP primers have independent collapse state', async ({ page }) => {
    await setupMocks(page);
    await clearScannerStorage(page);
    await page.goto('/options?ticker=F&strategy=covered_call');
    await page.waitForLoadState('networkidle');

    // Expand the CC primer.
    await page.getByTestId('scanner-strategy-primer-toggle').click();
    await expect(page.getByTestId('scanner-strategy-primer-body')).toBeVisible();

    // Toggle strategy to CSP via the filter button — CSP primer should be
    // collapsed (its own localStorage key is untouched).
    await page.getByRole('button', { name: 'Cash-Secured Put' }).click();
    await expect(page.getByTestId('scanner-strategy-primer-body')).toHaveCount(0);
    await expect(page.getByTestId('scanner-strategy-primer')).toHaveAttribute('data-strategy', 'csp');
  });
});

test.describe('Scanner education — column tooltips', () => {
  test('clicking ⓘ opens a 3-part tooltip; Escape closes it', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/options?ticker=F&strategy=covered_call&shares=100&cost_basis=13.2066');
    await page.waitForLoadState('networkidle');

    // Trigger a scan so the table (with column headers) renders.
    await page.getByRole('button', { name: 'Scan Options' }).click();
    await expect(page.getByTestId('strike-table')).toBeVisible();

    const deltaInfo = page.getByTestId('scanner-col-info-delta');
    await expect(deltaInfo).toBeVisible();

    // Tooltip closed initially.
    await expect(page.getByTestId('scanner-col-tooltip-delta')).toHaveCount(0);

    // Open by clicking.
    await deltaInfo.click();
    const tooltip = page.getByTestId('scanner-col-tooltip-delta');
    await expect(tooltip).toBeVisible();
    await expect(tooltip).toContainText('sensitivity to a $1 move');
    await expect(tooltip).toContainText('0.20 to 0.35');
    await expect(tooltip).toContainText('Stay in your comfort zone');

    // Escape closes.
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('scanner-col-tooltip-delta')).toHaveCount(0);
  });

  test('clicking the column label still triggers sort (independent of tooltip)', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/options?ticker=F&strategy=covered_call&shares=100&cost_basis=13.2066');
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: 'Scan Options' }).click();
    await expect(page.getByTestId('strike-table')).toBeVisible();

    // Sort by Delta — clicking the sort button should not open the tooltip.
    await page.getByTestId('scanner-col-sort-delta').click();
    await expect(page.getByTestId('scanner-col-tooltip-delta')).toHaveCount(0);
  });
});

test.describe('Scanner education — per-row expansion', () => {
  test('expanding a row reveals the "What this trade commits you to" panel', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/options?ticker=F&strategy=covered_call&shares=100&cost_basis=13.2066');
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: 'Scan Options' }).click();

    const table = page.getByTestId('strike-table');
    await expect(table).toBeVisible();

    // Commitment panel not visible while collapsed.
    await expect(page.getByTestId('scanner-strike-row-commitment')).toHaveCount(0);

    // Click the first row to expand.
    await table.locator('tbody tr').first().click();

    const commitment = page.getByTestId('scanner-strike-row-commitment');
    await expect(commitment).toBeVisible();
    await expect(commitment).toContainText('What this trade commits you to');
    // Outcome scenarios at expiration:
    await expect(commitment).toContainText('Stock stays below the strike');
    await expect(commitment).toContainText('Stock closes above the strike');
  });
});

test.describe('Scanner education — humanized rejected strikes', () => {
  test('renders human sentences from the backend, not raw codes', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/options?ticker=F&strategy=covered_call&shares=100&cost_basis=13.2066');
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: 'Scan Options' }).click();

    const disclosure = page.getByTestId('scanner-rejected-strikes');
    await expect(disclosure).toBeVisible();

    // Open the disclosure.
    await page.getByTestId('scanner-rejected-strikes-toggle').click();

    // Human sentence visible.
    await expect(disclosure).toContainText(
      'Strike sits -5.4% above your $13.21 basis'
    );
    await expect(disclosure).toContainText('Only 12 contracts open');

    // Raw machine code NOT visible to the user.
    await expect(disclosure).not.toContainText('fails_10pct_rule:');
    await expect(disclosure).not.toContainText('delta_out_of_range:');
    await expect(disclosure).not.toContainText('low_open_interest:');
  });
});
