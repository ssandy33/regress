import { test, expect } from '@playwright/test';

/**
 * E2E for issue #150 — Open Option Legs card upgrade.
 *
 * Covers AC:
 *   - %CAPTURED column renders `—` when state === "unknown" (universal V0.5)
 *   - RISK column reflects `legs[].assignment_risk` (high/watch/low)
 *   - ACTION column reflects `legs[].suggested_action` (roll/hold/manage —
 *     never "close" in V0.5 per spec §14.5)
 *   - Earnings ⚠ glyph in expiration cell when `earnings_in_window === true`,
 *     with `aria-label="Earnings before expiration"`.
 *   - Mobile breakpoint hides %CAPTURED and RISK columns.
 *   - Test IDs preserved: dashboard-leg-row.
 *   - New test IDs: dashboard-leg-row-captured, -risk, -action.
 */

const BASE_PAYLOAD = {
  generated_at: '2026-05-12T13:42:00+00:00',
  status: {
    schwab: { configured: true, valid: true, expires_at: '2026-08-01T00:00:00+00:00' },
    fred: { configured: true, valid: true },
    cache: { fresh: 12, stale: 0, very_stale: 0, total: 12 },
    journal: { positions_count: 1 },
  },
  kpis: {
    open_positions: 1,
    open_positions_breakdown: { stock: 0, csp: 0, cc: 0, wheel: 1, holding: 0 },
    notional_value: 17542,
    notional_change_pct: 0,
    open_legs: 3,
    open_legs_breakdown: { puts: 2, calls: 1 },
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
  upcoming_expirations: [],
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
    expiration: '2026-05-08',
    dte: 7,
    moneyness: { state: 'ITM', distance_pct: 0.0024, distance_dollars: 0.42 },
    position_id: 'pos-aapl',
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

test.describe('OpenLegsCard (V0.5 — triage columns)', () => {
  test('%CAPTURED column renders `—` when state is unknown (universal V0.5 case)', async ({ page }) => {
    const leg = makeLeg();
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [leg] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const captured = page.getByTestId('dashboard-leg-row-captured').first();
    await expect(captured).toBeVisible();
    await expect(captured).toContainText('—');
  });

  test('RISK column renders "High" with glyph for high-assignment-risk leg', async ({ page }) => {
    const leg = makeLeg({ assignment_risk: 'high', dte: 7 });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [leg] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const risk = page.getByTestId('dashboard-leg-row-risk').first();
    await expect(risk).toBeVisible();
    await expect(risk).toContainText('High');
  });

  test('assignment-risk thresholds: 14 DTE ITM = Watch, 21 DTE ITM = Low', async ({ page }) => {
    const watchLeg = makeLeg({
      id: 'leg-watch',
      ticker: 'TSLA',
      dte: 14,
      assignment_risk: 'watch',
      suggested_action: 'hold',
    });
    const lowLeg = makeLeg({
      id: 'leg-low',
      ticker: 'NVDA',
      dte: 21,
      assignment_risk: 'low',
      suggested_action: 'hold',
      moneyness: { state: 'OTM', distance_pct: 0.02, distance_dollars: 5 },
    });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [watchLeg, lowLeg] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const riskCells = page.getByTestId('dashboard-leg-row-risk');
    await expect(riskCells.nth(0)).toContainText('Watch');
    await expect(riskCells.nth(1)).toContainText('Low');
  });

  test('ACTION column reflects suggested_action — roll / hold / manage', async ({ page }) => {
    const rollLeg = makeLeg({ id: 'leg-roll', suggested_action: 'roll' });
    const holdLeg = makeLeg({
      id: 'leg-hold',
      ticker: 'TSLA',
      suggested_action: 'hold',
      assignment_risk: 'low',
      dte: 21,
    });
    const manageLeg = makeLeg({
      id: 'leg-manage',
      ticker: 'NVDA',
      suggested_action: 'manage',
      assignment_risk: 'watch',
      dte: 5,
      moneyness: { state: 'OTM', distance_pct: 0.02, distance_dollars: 5 },
    });
    await mockDashboard(page, {
      ...BASE_PAYLOAD,
      open_legs: [rollLeg, manageLeg, holdLeg],
    });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const actions = page.getByTestId('dashboard-leg-row-action');
    await expect(actions.nth(0)).toContainText('Roll');
    await expect(actions.nth(1)).toContainText('Manage');
    await expect(actions.nth(2)).toContainText('Hold');
  });

  test('earnings ⚠ glyph renders in expiration cell when earnings_in_window=true', async ({ page }) => {
    const leg = makeLeg({ earnings_in_window: true });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [leg] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const glyph = page.getByTestId('dashboard-leg-row-earnings').first();
    await expect(glyph).toBeVisible();
    await expect(glyph).toHaveAttribute('aria-label', 'Earnings before expiration');
  });

  test('earnings glyph hidden when earnings_in_window=false', async ({ page }) => {
    const leg = makeLeg({ earnings_in_window: false });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [leg] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    await expect(page.getByTestId('dashboard-leg-row-earnings')).toHaveCount(0);
  });

  test('mobile breakpoint (<lg) hides %CAPTURED and RISK columns', async ({ page }) => {
    const leg = makeLeg({ assignment_risk: 'high', suggested_action: 'roll' });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [leg] });
    await page.setViewportSize({ width: 600, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    // The cells carry the `hidden lg:block` classes; assert they are not
    // visible at this viewport.
    await expect(page.getByTestId('dashboard-leg-row-captured').first()).not.toBeVisible();
    await expect(page.getByTestId('dashboard-leg-row-risk').first()).not.toBeVisible();
    // The row itself is still visible
    await expect(page.getByTestId('dashboard-leg-row').first()).toBeVisible();
  });

  test('mobile ACTION column visible for urgent actions (roll/manage), hidden for hold', async ({ page }) => {
    const rollLeg = makeLeg({ id: 'leg-roll', suggested_action: 'roll' });
    const holdLeg = makeLeg({
      id: 'leg-hold',
      ticker: 'TSLA',
      suggested_action: 'hold',
      assignment_risk: 'low',
      dte: 21,
    });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [rollLeg, holdLeg] });
    await page.setViewportSize({ width: 600, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    // The roll action's label is visible (it's the urgent case).
    const actionCells = page.getByTestId('dashboard-leg-row-action');
    // The action text span inside the roll row is visible
    await expect(actionCells.nth(0).getByText('Roll', { exact: true })).toBeVisible();
    // The hold label is hidden on mobile (it carries `hidden lg:inline`)
    await expect(actionCells.nth(1).getByText('Hold', { exact: true })).not.toBeVisible();
  });
});
