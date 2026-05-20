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

    // 1-reason strike ($12.50) now renders the V1.0.8 near-pass framing
    // ('Would pass — …') instead of the legacy human_reasons[0] sentence.
    // 2-reason strike ($16.00) still renders the bulleted human_reasons.
    await expect(disclosure).toContainText('Would pass');
    await expect(disclosure).toContainText('Only 12 contracts open');

    // Raw machine code NOT visible to the user (still the canonical
    // humanization AC — applies to both the near-pass framed sentence and
    // the bulleted human-reasons branch).
    await expect(disclosure).not.toContainText('fails_10pct_rule:');
    await expect(disclosure).not.toContainText('delta_out_of_range:');
    await expect(disclosure).not.toContainText('low_open_interest:');
  });
});

// ============================================================================
// V1.0.8 / #257 — Rejected Strikes sort + summary + near-pass badge
// ============================================================================
//
// Appended block. Tests:
//   - Default sort = failure_count_asc — row order asserts 1-reason → 2 → 5.
//   - Clicking each sort header re-orders rows (strike, expiration, failures).
//   - Summary band renders chips count-desc; each chip has data-count.
//   - Near-pass badge renders ONLY on rows with rejection_reasons.length === 1.
//   - 3-tier stratification: 1 → near-pass badge; 2 → 'reasons' count text;
//     ≥3 → unchanged structural treatment.

// Multi-tier payload — five rejected strikes covering all three tiers.
// Row-by-row:
//   $13.50 / 2026-06-26 — 1 reason   (near-pass, delta out of range)
//   $14.00 / 2026-06-26 — 1 reason   (near-pass, low open interest)
//   $13.00 / 2026-07-31 — 2 reasons  (normal)
//   $5.00  / 2026-06-26 — 5 reasons  (structural — below cost basis dominates)
//   $6.00  / 2026-07-31 — 5 reasons  (structural)
// Rule-family counts across all five strikes:
//   below_cost_basis        : 2  ($5.00, $6.00)
//   delta_out_of_range      : 4  ($13.50, $13.00, $5.00, $6.00)
//   low_open_interest       : 4  ($14.00, $13.00, $5.00, $6.00)
//   wide_bid_ask_spread     : 2  ($5.00, $6.00)
//   fails_10pct_rule        : 2  ($5.00, $6.00)
// Order count-desc, canonical-order tie-break:
//   delta_out_of_range (4), low_open_interest (4), fails_10pct_rule (2),
//   below_cost_basis (2), wide_bid_ask_spread (2)
const TIERED_SCAN_PAYLOAD = {
  ticker: 'F',
  current_price: 13.21,
  strategy: 'covered_call',
  scan_time: '2026-05-20T12:00:00Z',
  earnings_date: null,
  iv_rank: null,
  recommendations: [],
  rejected: [
    // Index 0 — 1 reason (near-pass, delta)
    {
      strike: 13.5,
      expiration: '2026-06-26',
      rejection_reasons: ['delta_out_of_range: |0.38| not in [0.20, 0.35]'],
      human_reasons: [
        'Delta +0.38 is outside your 0.20–0.35 range — too close to the money.',
      ],
    },
    // Index 1 — 1 reason (near-pass, OI)
    {
      strike: 14.0,
      expiration: '2026-06-26',
      rejection_reasons: ['low_open_interest: 25 < 50'],
      human_reasons: [
        'Only 25 contracts open — too thin to trade comfortably (the scanner requires at least 50).',
      ],
    },
    // Index 2 — 2 reasons (normal)
    {
      strike: 13.0,
      expiration: '2026-07-31',
      rejection_reasons: [
        'delta_out_of_range: |0.42| not in [0.20, 0.35]',
        'low_open_interest: 18 < 50',
      ],
      human_reasons: [
        'Delta +0.42 is outside your 0.20–0.35 range — too close to the money.',
        'Only 18 contracts open — too thin to trade comfortably (the scanner requires at least 50).',
      ],
    },
    // Index 3 — 5 reasons (structural)
    {
      strike: 5.0,
      expiration: '2026-06-26',
      rejection_reasons: [
        'fails_10pct_rule: strike -62.2% above basis, requires 10.0%',
        'below_cost_basis: strike $5.00 < floor $13.21',
        'delta_out_of_range: |0.92| not in [0.20, 0.35]',
        'low_open_interest: 8 < 50',
        'wide_bid_ask_spread: 22.5% > 10.0%',
      ],
      human_reasons: [
        'Strike sits -62.2% above your $13.21 basis, but the 10.0% rule requires at least that much room.',
        'Strike $5.00 is below your $13.21 cost-basis floor — if assigned, you would lock in a loss on the shares.',
        'Delta +0.92 is outside your 0.20–0.35 range — too close to the money.',
        'Only 8 contracts open — too thin to trade comfortably (the scanner requires at least 50).',
        'The bid/ask spread is 22.5% of the mid price — wider than your 10.0% limit.',
      ],
    },
    // Index 4 — 5 reasons (structural)
    {
      strike: 6.0,
      expiration: '2026-07-31',
      rejection_reasons: [
        'fails_10pct_rule: strike -54.6% above basis, requires 10.0%',
        'below_cost_basis: strike $6.00 < floor $13.21',
        'delta_out_of_range: |0.88| not in [0.20, 0.35]',
        'low_open_interest: 12 < 50',
        'wide_bid_ask_spread: 18.0% > 10.0%',
      ],
      human_reasons: [
        'Strike sits -54.6% above your $13.21 basis, but the 10.0% rule requires at least that much room.',
        'Strike $6.00 is below your $13.21 cost-basis floor — if assigned, you would lock in a loss on the shares.',
        'Delta +0.88 is outside your 0.20–0.35 range — too close to the money.',
        'Only 12 contracts open — too thin to trade comfortably (the scanner requires at least 50).',
        'The bid/ask spread is 18.0% of the mid price — wider than your 10.0% limit.',
      ],
    },
  ],
  market_context: {},
};

function setupTieredMocks(page) {
  return Promise.all([
    page.route('**/api/settings/health/schwab', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          configured: true,
          valid: true,
          error: null,
          token_expiry: null,
        }),
      })
    ),
    page.route('**/api/options/scan', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(TIERED_SCAN_PAYLOAD),
      })
    ),
  ]);
}

// Helper — open the panel and return the locator for all row strike+exp labels
// in DOM order. We read the first <span> in each row (the "$X.XX YYYY-MM-DD"
// header text) so we can assert on the order without depending on the badge
// chrome.
async function openPanelAndGetRowLabels(page) {
  await page.getByTestId('scanner-rejected-strikes-toggle').click();
  const rows = page.getByTestId('scanner-rejected-strike-row');
  await expect(rows.first()).toBeVisible();
  return rows.locator('> div > span').first();
}

test.describe('Scanner education — Rejected Strikes sort + summary + near-pass (#257)', () => {
  test('default sort is failure_count_asc — 1-reason rows surface first', async ({
    page,
  }) => {
    await setupTieredMocks(page);
    await page.goto('/options?ticker=F&strategy=covered_call&shares=100&cost_basis=13.21');
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: 'Scan Options' }).click();

    await expect(page.getByTestId('scanner-rejected-strikes')).toBeVisible();
    await page.getByTestId('scanner-rejected-strikes-toggle').click();

    const rows = page.getByTestId('scanner-rejected-strike-row');
    await expect(rows).toHaveCount(5);

    // Default sort = failure_count asc — order:
    //   1-reason rows first (in payload order: $13.50, $14.00),
    //   then 2-reason ($13.00),
    //   then 5-reason ($5.00, $6.00).
    await expect(rows.nth(0)).toContainText('$13.50');
    await expect(rows.nth(1)).toContainText('$14.00');
    await expect(rows.nth(2)).toContainText('$13.00');
    await expect(rows.nth(3)).toContainText('$5.00');
    await expect(rows.nth(4)).toContainText('$6.00');

    // Active sort header carries the asc arrow (↑).
    await expect(page.getByTestId('scanner-rejected-strikes-sort-failure_count')).toContainText('↑');
  });

  test('clicking Strike sort reorders rows by strike asc; toggling reverses to desc', async ({
    page,
  }) => {
    await setupTieredMocks(page);
    await page.goto('/options?ticker=F&strategy=covered_call&shares=100&cost_basis=13.21');
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: 'Scan Options' }).click();
    await page.getByTestId('scanner-rejected-strikes-toggle').click();

    await page.getByTestId('scanner-rejected-strikes-sort-strike').click();

    const rows = page.getByTestId('scanner-rejected-strike-row');
    await expect(rows.nth(0)).toContainText('$5.00');
    await expect(rows.nth(1)).toContainText('$6.00');
    await expect(rows.nth(2)).toContainText('$13.00');
    await expect(rows.nth(3)).toContainText('$13.50');
    await expect(rows.nth(4)).toContainText('$14.00');

    // Active header has the asc arrow.
    await expect(page.getByTestId('scanner-rejected-strikes-sort-strike')).toContainText('↑');

    // Clicking the active header again toggles to desc.
    await page.getByTestId('scanner-rejected-strikes-sort-strike').click();
    await expect(rows.nth(0)).toContainText('$14.00');
    await expect(rows.nth(4)).toContainText('$5.00');
    await expect(page.getByTestId('scanner-rejected-strikes-sort-strike')).toContainText('↓');
  });

  test('clicking Expiration sort reorders rows by ISO date asc', async ({
    page,
  }) => {
    await setupTieredMocks(page);
    await page.goto('/options?ticker=F&strategy=covered_call&shares=100&cost_basis=13.21');
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: 'Scan Options' }).click();
    await page.getByTestId('scanner-rejected-strikes-toggle').click();

    await page.getByTestId('scanner-rejected-strikes-sort-expiration').click();

    const rows = page.getByTestId('scanner-rejected-strike-row');
    // 2026-06-26 group first (payload-stable inside the group): $13.50, $14.00, $5.00
    // Then 2026-07-31: $13.00, $6.00
    await expect(rows.nth(0)).toContainText('2026-06-26');
    await expect(rows.nth(1)).toContainText('2026-06-26');
    await expect(rows.nth(2)).toContainText('2026-06-26');
    await expect(rows.nth(3)).toContainText('2026-07-31');
    await expect(rows.nth(4)).toContainText('2026-07-31');

    await expect(page.getByTestId('scanner-rejected-strikes-sort-expiration')).toContainText('↑');
  });

  test('clicking the active failure_count sort toggles asc → desc; 5-reason rows surface first', async ({
    page,
  }) => {
    await setupTieredMocks(page);
    await page.goto('/options?ticker=F&strategy=covered_call&shares=100&cost_basis=13.21');
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: 'Scan Options' }).click();
    await page.getByTestId('scanner-rejected-strikes-toggle').click();

    // failure_count is already active (default) — click toggles to desc.
    await page.getByTestId('scanner-rejected-strikes-sort-failure_count').click();

    const rows = page.getByTestId('scanner-rejected-strike-row');
    await expect(rows.nth(0)).toContainText('$5.00');
    await expect(rows.nth(1)).toContainText('$6.00');
    await expect(rows.nth(2)).toContainText('$13.00');
    // Near-pass rows sink to the bottom.
    await expect(rows.nth(3)).toContainText('$13.50');
    await expect(rows.nth(4)).toContainText('$14.00');

    await expect(page.getByTestId('scanner-rejected-strikes-sort-failure_count')).toContainText('↓');
  });

  test('summary band renders chips count-desc with data-count attributes', async ({
    page,
  }) => {
    await setupTieredMocks(page);
    await page.goto('/options?ticker=F&strategy=covered_call&shares=100&cost_basis=13.21');
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: 'Scan Options' }).click();
    await page.getByTestId('scanner-rejected-strikes-toggle').click();

    const summary = page.getByTestId('scanner-rejected-strikes-summary');
    await expect(summary).toBeVisible();
    await expect(summary).toContainText('Of 5 rejected:');

    // Counts (per-strike dedupe inside the aggregator):
    //   delta_out_of_range: 4, low_open_interest: 4, fails_10pct_rule: 2,
    //   below_cost_basis: 2, wide_bid_ask_spread: 2.
    await expect(
      page.getByTestId('scanner-rejected-strikes-summary-rule-delta_out_of_range')
    ).toHaveAttribute('data-count', '4');
    await expect(
      page.getByTestId('scanner-rejected-strikes-summary-rule-low_open_interest')
    ).toHaveAttribute('data-count', '4');
    await expect(
      page.getByTestId('scanner-rejected-strikes-summary-rule-fails_10pct_rule')
    ).toHaveAttribute('data-count', '2');
    await expect(
      page.getByTestId('scanner-rejected-strikes-summary-rule-below_cost_basis')
    ).toHaveAttribute('data-count', '2');
    await expect(
      page.getByTestId('scanner-rejected-strikes-summary-rule-wide_bid_ask_spread')
    ).toHaveAttribute('data-count', '2');

    // Chip labels come from REJECTION_RULE_LABELS — assert the human labels
    // render, not raw machine codes.
    await expect(summary).toContainText('Delta');
    await expect(summary).toContainText('Open interest');
    await expect(summary).toContainText('Distance from basis');
    await expect(summary).toContainText('Cost basis');
    await expect(summary).toContainText('Spread');

    // DOM order: count-desc, with canonical-rule-order tie-break. The two
    // count-4 chips come first; delta_out_of_range precedes low_open_interest
    // in canonical order. Among the count-2 chips, fails_10pct_rule precedes
    // below_cost_basis precedes wide_bid_ask_spread.
    const chips = summary.locator('button[data-testid^="scanner-rejected-strikes-summary-rule-"]');
    await expect(chips).toHaveCount(5);
    await expect(chips.nth(0)).toHaveAttribute(
      'data-testid',
      'scanner-rejected-strikes-summary-rule-delta_out_of_range'
    );
    await expect(chips.nth(1)).toHaveAttribute(
      'data-testid',
      'scanner-rejected-strikes-summary-rule-low_open_interest'
    );
    await expect(chips.nth(2)).toHaveAttribute(
      'data-testid',
      'scanner-rejected-strikes-summary-rule-fails_10pct_rule'
    );
    await expect(chips.nth(3)).toHaveAttribute(
      'data-testid',
      'scanner-rejected-strikes-summary-rule-below_cost_basis'
    );
    await expect(chips.nth(4)).toHaveAttribute(
      'data-testid',
      'scanner-rejected-strikes-summary-rule-wide_bid_ask_spread'
    );
  });

  test('near-pass badge renders only on rows with exactly 1 rejection reason; 3-tier stratification', async ({
    page,
  }) => {
    await setupTieredMocks(page);
    await page.goto('/options?ticker=F&strategy=covered_call&shares=100&cost_basis=13.21');
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: 'Scan Options' }).click();
    await page.getByTestId('scanner-rejected-strikes-toggle').click();

    const rows = page.getByTestId('scanner-rejected-strike-row');
    await expect(rows).toHaveCount(5);

    // Exactly two near-pass badges in total — one per single-reason row.
    const badges = page.getByTestId('scanner-rejected-strike-badge-near-pass');
    await expect(badges).toHaveCount(2);
    await expect(badges.first()).toContainText('One rule away');

    // Tier 1 — near-pass rows have the badge and the fact-led 'Would pass —'
    // sentence; the '1 reason' text MUST NOT appear in those rows.
    const nearPassRow1 = rows.nth(0);
    await expect(nearPassRow1).toContainText('$13.50');
    await expect(
      nearPassRow1.getByTestId('scanner-rejected-strike-badge-near-pass')
    ).toBeVisible();
    await expect(nearPassRow1).toContainText('Would pass');
    await expect(nearPassRow1).toContainText('delta 0.38');
    await expect(nearPassRow1).toContainText('0.03 over');
    await expect(nearPassRow1).not.toContainText('1 reason');

    const nearPassRow2 = rows.nth(1);
    await expect(nearPassRow2).toContainText('$14.00');
    await expect(
      nearPassRow2.getByTestId('scanner-rejected-strike-badge-near-pass')
    ).toBeVisible();
    await expect(nearPassRow2).toContainText('Would pass');
    await expect(nearPassRow2).toContainText('open interest 25');
    await expect(nearPassRow2).toContainText('25 short');

    // Tier 2 — normal row (2 reasons): no near-pass badge, '2 reasons' text,
    // bulleted human sentences (unchanged from pre-#257 treatment).
    const normalRow = rows.nth(2);
    await expect(normalRow).toContainText('$13.00');
    await expect(
      normalRow.getByTestId('scanner-rejected-strike-badge-near-pass')
    ).toHaveCount(0);
    await expect(normalRow).toContainText('2 reasons');
    await expect(normalRow).toContainText('Delta +0.42');
    await expect(normalRow).toContainText('Only 18 contracts open');

    // Tier 3 — structural row (5 reasons): no near-pass badge, bulleted list.
    // Since #259 (W-E) merged, ≥3-reason rows render collapsed by default —
    // expand via the group toggle so the bulleted reason text becomes
    // assertable. (The pre-merge phrasing '5 reasons' is now '5 reasons hidden'
    // in the collapsed state — `toContainText('5 reasons')` still matches as
    // a substring either way.)
    const structuralRow = rows.nth(3);
    await expect(structuralRow).toContainText('$5.00');
    await expect(
      structuralRow.getByTestId('scanner-rejected-strike-badge-near-pass')
    ).toHaveCount(0);
    await expect(structuralRow).toContainText('5 reasons');
    await structuralRow.getByTestId('scanner-rejected-strike-group-toggle').click();
    await expect(structuralRow).toContainText('cost-basis floor');
  });
});

// ============================================================================
// V1.0.8 / #259 — Collapse-by-default for rejected strikes with ≥3 reasons
// ============================================================================
//
// Appended block (S1 — append-only). Tests:
//   - Default render: a row with `rejection_reasons.length >= 3` is wrapped
//     in `scanner-rejected-strike-group` with `data-collapsed="true"`.
//   - Toggling `Show ▾` on any group flips the single global flag —
//     EVERY ≥3-reason row's `data-collapsed` flips to `"false"`.
//   - localStorage key `scanner-rejected-strikes-row-collapsed` persists
//     across `page.reload()`.
//   - Rows with `<3` reasons are NOT wrapped in the collapse group
//     (no `scanner-rejected-strike-group` testid).
//   - Threshold boundary: exactly 3 reasons → collapsible; exactly 2 → not.
//
// Reuses TIERED_SCAN_PAYLOAD and setupTieredMocks defined above (5 rejected
// strikes: 1, 1, 2, 5, 5 reasons — gives us 2 ≥3-reason groups for the
// "all flip together" assertion). A separate BOUNDARY_SCAN_PAYLOAD covers the
// 3-vs-2 threshold edge.

// Boundary payload — two rejected strikes, one with exactly 2 reasons
// (NOT collapsible) and one with exactly 3 reasons (collapsible). Asserts
// the `>= 3` threshold inclusively.
const BOUNDARY_SCAN_PAYLOAD = {
  ticker: 'F',
  current_price: 13.21,
  strategy: 'covered_call',
  scan_time: '2026-05-20T12:00:00Z',
  earnings_date: null,
  iv_rank: null,
  recommendations: [],
  rejected: [
    // 2-reason row — NOT collapsible (just below the threshold).
    {
      strike: 13.0,
      expiration: '2026-07-31',
      rejection_reasons: [
        'delta_out_of_range: |0.42| not in [0.20, 0.35]',
        'low_open_interest: 18 < 50',
      ],
      human_reasons: [
        'Delta +0.42 is outside your 0.20–0.35 range — too close to the money.',
        'Only 18 contracts open — too thin to trade comfortably (the scanner requires at least 50).',
      ],
    },
    // 3-reason row — collapsible exactly at the threshold.
    {
      strike: 7.0,
      expiration: '2026-07-31',
      rejection_reasons: [
        'fails_10pct_rule: strike -47.0% above basis, requires 10.0%',
        'delta_out_of_range: |0.85| not in [0.20, 0.35]',
        'low_open_interest: 11 < 50',
      ],
      human_reasons: [
        'Strike sits -47.0% above your $13.21 basis, but the 10.0% rule requires at least that much room.',
        'Delta +0.85 is outside your 0.20–0.35 range — too close to the money.',
        'Only 11 contracts open — too thin to trade comfortably (the scanner requires at least 50).',
      ],
    },
  ],
  market_context: {},
};

function setupBoundaryMocks(page) {
  return Promise.all([
    page.route('**/api/settings/health/schwab', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          configured: true,
          valid: true,
          error: null,
          token_expiry: null,
        }),
      })
    ),
    page.route('**/api/options/scan', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(BOUNDARY_SCAN_PAYLOAD),
      })
    ),
  ]);
}

// Helper — clear the row-collapse localStorage key so the default-collapsed
// branch is exercised deterministically. We `goto('/options')` first so the
// page origin is available to `localStorage.removeItem`. Mirrors
// `clearScannerStorage` above; kept local to the #259 block so it does not
// disturb upstream tests.
async function clearRowCollapseStorage(page) {
  await page.goto('/options');
  await page.evaluate(() => {
    try {
      window.localStorage.removeItem('scanner-rejected-strikes-row-collapsed');
    } catch {
      // ignore
    }
  });
}

test.describe('Scanner education — Rejected Strikes ≥3-reason collapse (#259)', () => {
  test('rows with >= 3 reasons render collapsed by default (data-collapsed="true")', async ({
    page,
  }) => {
    await setupTieredMocks(page);
    await clearRowCollapseStorage(page);
    await page.goto('/options?ticker=F&strategy=covered_call&shares=100&cost_basis=13.21');
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: 'Scan Options' }).click();
    await page.getByTestId('scanner-rejected-strikes-toggle').click();

    // Two ≥3-reason groups in the tiered payload (the two 5-reason rows).
    const groups = page.getByTestId('scanner-rejected-strike-group');
    await expect(groups).toHaveCount(2);

    // Both render collapsed on first visit (default = true).
    await expect(groups.nth(0)).toHaveAttribute('data-collapsed', 'true');
    await expect(groups.nth(1)).toHaveAttribute('data-collapsed', 'true');

    // Each collapsed group exposes a `Show ▾` toggle and the "N reasons hidden"
    // phrase — and the reason bullets are NOT in the DOM yet.
    const toggles = page.getByTestId('scanner-rejected-strike-group-toggle');
    await expect(toggles).toHaveCount(2);
    await expect(toggles.first()).toContainText('Show');
    await expect(groups.first()).toContainText('5 reasons hidden');
    await expect(groups.first()).not.toContainText('cost-basis floor');
  });

  test('clicking Show on one ≥3-reason group expands ALL ≥3-reason groups (single global flag)', async ({
    page,
  }) => {
    await setupTieredMocks(page);
    await clearRowCollapseStorage(page);
    await page.goto('/options?ticker=F&strategy=covered_call&shares=100&cost_basis=13.21');
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: 'Scan Options' }).click();
    await page.getByTestId('scanner-rejected-strikes-toggle').click();

    const groups = page.getByTestId('scanner-rejected-strike-group');
    await expect(groups).toHaveCount(2);

    // Click the first group's toggle — the single global flag flips, so
    // BOTH groups expand simultaneously.
    await page
      .getByTestId('scanner-rejected-strike-group-toggle')
      .first()
      .click();

    await expect(groups.nth(0)).toHaveAttribute('data-collapsed', 'false');
    await expect(groups.nth(1)).toHaveAttribute('data-collapsed', 'false');

    // Bullet text is now rendered in both groups; toggle wording flips to Hide.
    await expect(groups.nth(0)).toContainText('cost-basis floor');
    await expect(groups.nth(1)).toContainText('cost-basis floor');
    await expect(
      page.getByTestId('scanner-rejected-strike-group-toggle').first()
    ).toContainText('Hide');

    // Clicking Hide on the second group re-collapses both.
    await page
      .getByTestId('scanner-rejected-strike-group-toggle')
      .nth(1)
      .click();
    await expect(groups.nth(0)).toHaveAttribute('data-collapsed', 'true');
    await expect(groups.nth(1)).toHaveAttribute('data-collapsed', 'true');
  });

  test('collapse state persists across page reload via localStorage', async ({ page }) => {
    await setupTieredMocks(page);
    await clearRowCollapseStorage(page);
    await page.goto('/options?ticker=F&strategy=covered_call&shares=100&cost_basis=13.21');
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: 'Scan Options' }).click();
    await page.getByTestId('scanner-rejected-strikes-toggle').click();

    // Expand — flag flips to '0'.
    await page
      .getByTestId('scanner-rejected-strike-group-toggle')
      .first()
      .click();
    await expect(
      page.getByTestId('scanner-rejected-strike-group').first()
    ).toHaveAttribute('data-collapsed', 'false');

    // Inspect the localStorage value directly — boolean '0' (expanded).
    const stored = await page.evaluate(() =>
      window.localStorage.getItem('scanner-rejected-strikes-row-collapsed')
    );
    expect(stored).toBe('0');

    // Reload — the expanded state survives (need to re-open the panel and
    // re-run the scan because the panel mock state does not auto-persist).
    await page.reload();
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: 'Scan Options' }).click();
    await page.getByTestId('scanner-rejected-strikes-toggle').click();

    const groups = page.getByTestId('scanner-rejected-strike-group');
    await expect(groups.first()).toHaveAttribute('data-collapsed', 'false');
    await expect(groups.first()).toContainText('cost-basis floor');
  });

  test('rows with < 3 reasons are NOT wrapped in the collapse group', async ({
    page,
  }) => {
    await setupTieredMocks(page);
    await clearRowCollapseStorage(page);
    await page.goto('/options?ticker=F&strategy=covered_call&shares=100&cost_basis=13.21');
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: 'Scan Options' }).click();
    await page.getByTestId('scanner-rejected-strikes-toggle').click();

    // The tiered payload has 5 rejected strikes — 1, 1, 2, 5, 5 reasons.
    // Only the two 5-reason rows are wrapped; the three rows with <3
    // reasons render the normal treatment (no group testid, no toggle).
    const groups = page.getByTestId('scanner-rejected-strike-group');
    const toggles = page.getByTestId('scanner-rejected-strike-group-toggle');
    await expect(groups).toHaveCount(2);
    await expect(toggles).toHaveCount(2);

    // Row 2 of the default sort (`failure_count_asc`) is the 2-reason row —
    // it must not carry the group testid or the toggle.
    const rows = page.getByTestId('scanner-rejected-strike-row');
    const twoReasonRow = rows.nth(2);
    await expect(twoReasonRow).toContainText('$13.00');
    await expect(twoReasonRow).toContainText('2 reasons');
    await expect(
      twoReasonRow.getByTestId('scanner-rejected-strike-group')
    ).toHaveCount(0);
    await expect(
      twoReasonRow.getByTestId('scanner-rejected-strike-group-toggle')
    ).toHaveCount(0);
  });

  test('threshold boundary — exactly 3 reasons collapses, exactly 2 does not', async ({
    page,
  }) => {
    await setupBoundaryMocks(page);
    await clearRowCollapseStorage(page);
    await page.goto('/options?ticker=F&strategy=covered_call&shares=100&cost_basis=13.21');
    await page.waitForLoadState('networkidle');
    await page.getByRole('button', { name: 'Scan Options' }).click();
    await page.getByTestId('scanner-rejected-strikes-toggle').click();

    // Exactly one collapsible group — the 3-reason row.
    const groups = page.getByTestId('scanner-rejected-strike-group');
    await expect(groups).toHaveCount(1);
    await expect(groups.first()).toHaveAttribute('data-collapsed', 'true');
    await expect(groups.first()).toContainText('3 reasons hidden');

    // The 2-reason row is rendered as a normal row (no group testid).
    // Default sort = failure_count_asc, so rows.nth(0) is the 2-reason row
    // ($13.00) and rows.nth(1) is the 3-reason row ($7.00).
    const rows = page.getByTestId('scanner-rejected-strike-row');
    await expect(rows).toHaveCount(2);
    const twoReasonRow = rows.nth(0);
    await expect(twoReasonRow).toContainText('$13.00');
    await expect(twoReasonRow).toContainText('2 reasons');
    await expect(
      twoReasonRow.getByTestId('scanner-rejected-strike-group')
    ).toHaveCount(0);

    // Sanity check — the 3-reason row IS the collapsible group.
    const threeReasonRow = rows.nth(1);
    await expect(threeReasonRow).toContainText('$7.00');
    await expect(
      threeReasonRow.getByTestId('scanner-rejected-strike-group')
    ).toHaveCount(1);
  });
});
