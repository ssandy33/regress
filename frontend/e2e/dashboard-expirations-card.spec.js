import { test, expect } from '@playwright/test';

/**
 * E2E for issue #149 — Upcoming Expirations card upgrade.
 *
 * Covers AC:
 *   - Line 1 identity + decision tag pill (existing — preserved)
 *   - Line 2 moneyness clause + premium-remaining clause.
 *     Premium-remaining MUST render `—` when
 *     `profit_target_status.state === "unknown"` (universal V0.5 state).
 *   - Line 3 conditional: renders only when `earnings_in_window === true`
 *     OR DTE ≤ 7. Hidden otherwise.
 *   - Empty states: no-open-legs vs open-legs-but-none-near.
 *   - Test IDs: dashboard-expiration-row, dashboard-expiration-row-earnings.
 */

const BASE_PAYLOAD = {
  generated_at: '2026-05-12T13:42:00+00:00',
  status: {
    schwab: { configured: true, valid: true, expires_at: '2026-08-01T00:00:00+00:00' },
    fred: { configured: true, valid: true },
    cache: { fresh: 12, stale: 0, very_stale: 0, total: 12 },
    journal: { positions_count: 2 },
  },
  kpis: {
    open_positions: 2,
    open_positions_breakdown: { stock: 0, csp: 0, cc: 0, wheel: 2, holding: 0 },
    notional_value: 10000,
    notional_change_pct: 0,
    open_legs: 2,
    open_legs_breakdown: { puts: 1, calls: 1 },
    unrealized_pl: 0,
    unrealized_pl_pct: 0,
    largest_risk: null,
    premium_collected_total: 0,
    premium_collected_trades: 0,
    premium_collected_ytd: 0,
    realized_pl: 0,
    realized_pl_pct: null,
    largest_loser: null,
  },
  positions: [
    {
      id: 'pos-aapl',
      ticker: 'AAPL',
      shares: 100,
      strategy: 'wheel',
      adjusted_cost_basis: 17240.0,
      current_price: 175.42,
      notional: 17542.0,
      unrealized_pl: 0,
      open_legs_count: 1,
    },
  ],
  open_legs: [],
  recent_activity: [],
  data_meta: {
    is_stale: false,
    fetched_at: '2026-05-12T13:42:00+00:00',
    sources_unavailable: [],
  },
};

function makeLeg(overrides = {}) {
  return {
    id: 'leg-1',
    ticker: 'AAPL',
    type: 'put',
    strike: 175.0,
    expiration: '2026-05-15',
    dte: 3,
    moneyness: { state: 'ITM', distance_pct: 0.0024, distance_dollars: 0.42 },
    position_id: 'pos-aapl',
    decision_tag: 'roll-or-assign',
    decision_reason: 'ITM by $0.42',
    profit_target_status: { captured_pct: null, state: 'unknown' },
    assignment_risk: 'high',
    suggested_action: 'roll',
    earnings_in_window: false,
    ...overrides,
  };
}

function mockDashboard(page, payload) {
  return page.route('**/api/dashboard', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(payload),
    })
  );
}

test.describe('UpcomingExpirationsCard (V0.5 — densified rows)', () => {
  test('renders identity, decision tag, moneyness, and premium-remaining `—`', async ({ page }) => {
    const leg = makeLeg({ earnings_in_window: false, dte: 3 });
    await mockDashboard(page, {
      ...BASE_PAYLOAD,
      upcoming_expirations: [leg],
      open_legs: [leg],
    });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const row = page.getByTestId('dashboard-expiration-row').first();
    await expect(row).toBeVisible();
    // Line 1 — identity + DTE + decision tag pill
    await expect(row).toContainText('AAPL');
    await expect(row).toContainText('175');
    await expect(row).toContainText('Roll or assign');
    // Line 2 — moneyness clause and premium-remaining `—` (state === unknown)
    await expect(row).toContainText('ITM by $0.42');
    await expect(row).toContainText('Premium remaining —');
  });

  test('line 3 earnings warning renders when earnings_in_window === true', async ({ page }) => {
    const leg = makeLeg({ earnings_in_window: true, dte: 3 });
    await mockDashboard(page, {
      ...BASE_PAYLOAD,
      upcoming_expirations: [leg],
      open_legs: [leg],
    });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const row = page.getByTestId('dashboard-expiration-row').first();
    const earnings = row.getByTestId('dashboard-expiration-row-earnings');
    await expect(earnings).toBeVisible();
    // Earnings text prefixed with the word "Earnings" (a11y — not just glyph)
    await expect(earnings).toContainText('Earnings');
  });

  test('line 3 renders suggested-window when DTE ≤ 7 and no earnings', async ({ page }) => {
    const leg = makeLeg({ earnings_in_window: false, dte: 3 });
    await mockDashboard(page, {
      ...BASE_PAYLOAD,
      upcoming_expirations: [leg],
      open_legs: [leg],
    });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const earnings = page.getByTestId('dashboard-expiration-row-earnings').first();
    await expect(earnings).toBeVisible();
    // No earnings prefix; suggested-window phrase instead.
    await expect(earnings).not.toContainText('Earnings');
    await expect(earnings).toContainText(/Roll/i);
  });

  test('line 3 hidden when no earnings AND DTE > 7', async ({ page }) => {
    const leg = makeLeg({
      earnings_in_window: false,
      dte: 10,
      decision_tag: 'hold',
      assignment_risk: 'low',
      suggested_action: 'hold',
      moneyness: { state: 'OTM', distance_pct: 0.041, distance_dollars: 1.2 },
    });
    await mockDashboard(page, {
      ...BASE_PAYLOAD,
      upcoming_expirations: [leg],
      open_legs: [leg],
    });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    await expect(page.getByTestId('dashboard-expiration-row-earnings')).toHaveCount(0);
  });

  test('premium-remaining shows `—` even when captured_pct is non-null (state must dominate)', async ({ page }) => {
    // Defensive: backend should never emit captured_pct without state !== "unknown",
    // but the frontend MUST treat state === "unknown" as authoritative per spec §14.5.
    const leg = makeLeg({
      profit_target_status: { captured_pct: 0.6, state: 'unknown' },
    });
    await mockDashboard(page, {
      ...BASE_PAYLOAD,
      upcoming_expirations: [leg],
      open_legs: [leg],
    });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    await expect(page.getByTestId('dashboard-expiration-row').first()).toContainText('Premium remaining —');
  });

  test('empty state when no open legs at all', async ({ page }) => {
    await mockDashboard(page, {
      ...BASE_PAYLOAD,
      kpis: { ...BASE_PAYLOAD.kpis, open_legs: 0, open_legs_breakdown: { puts: 0, calls: 0 } },
      upcoming_expirations: [],
      open_legs: [],
    });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const empty = page.getByTestId('dashboard-expirations-empty-no-legs');
    await expect(empty).toBeVisible();
    await expect(empty).toContainText('No open option legs');
    await expect(empty.getByRole('link', { name: /Run scanner/i })).toBeVisible();
  });

  test('empty state when open legs exist but none in 14-day window', async ({ page }) => {
    const farLeg = makeLeg({
      id: 'leg-far',
      dte: 45,
      earnings_in_window: false,
      decision_tag: 'hold',
    });
    await mockDashboard(page, {
      ...BASE_PAYLOAD,
      kpis: { ...BASE_PAYLOAD.kpis, open_legs: 1, open_legs_breakdown: { puts: 1, calls: 0 } },
      upcoming_expirations: [],
      open_legs: [farLeg],
    });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const empty = page.getByTestId('dashboard-expirations-empty-no-near');
    await expect(empty).toBeVisible();
    await expect(empty).toContainText(/Nothing expiring in the next 14 days/);
  });
});
