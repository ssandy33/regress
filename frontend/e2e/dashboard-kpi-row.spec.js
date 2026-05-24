import { test, expect } from '@playwright/test';

/**
 * E2E for issue #148 — KPI row extended to 7 tiles.
 *
 * Covers AC:
 *   - 7 visible tiles (4 existing + Largest risk + Realized P/L + Premium)
 *   - Each new tile populated with non-null data
 *   - Each new tile renders the locked empty-state copy (largest_risk `—`;
 *     realized_pl `$0` / `0%`; premium `$0` / `0 trades`)
 *   - Tooltip text on Largest risk
 *   - Payload-only fields (premium_collected_ytd, largest_loser) are NOT
 *     rendered as visible tiles
 *   - Breakpoint behavior: 7 columns at lg+, 3 columns at md, 2 columns at sm
 *   - Test IDs: kpi-largest-risk, kpi-realized-pl, kpi-premium-lifetime
 */

const BASE_PAYLOAD = {
  generated_at: '2026-05-12T13:42:00+00:00',
  status: {
    schwab: { configured: true, valid: true, expires_at: '2026-08-01T00:00:00+00:00' },
    fred: { configured: true, valid: true },
    cache: { fresh: 12, stale: 0, very_stale: 0, total: 12 },
    journal: { positions_count: 2 },
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
      unrealized_pl: 302.0,
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

const POPULATED_KPIS = {
  open_positions: 4,
  open_positions_breakdown: { stock: 0, csp: 1, cc: 0, wheel: 2, holding: 1 },
  notional_value: 48210.0,
  notional_change_pct: 0.021,
  open_legs: 7,
  open_legs_breakdown: { puts: 4, calls: 3 },
  unrealized_pl: 612.0,
  unrealized_pl_pct: 0.013,
  largest_risk: {
    ticker: 'TSLA',
    unrealized_pl: -1420.0,
    unrealized_pl_pct: -0.072,
  },
  premium_collected_total: 2847.0,
  premium_collected_trades: 38,
  premium_collected_ytd: 1200.0,
  realized_pl: 1932.0,
  realized_pl_pct: 0.041,
  // Payload-only — must NOT render as a tile
  largest_loser: { ticker: 'AMD', realized_pl: -420.0, realized_pl_pct: -0.03 },
};

const EMPTY_KPIS = {
  open_positions: 0,
  open_positions_breakdown: { stock: 0, csp: 0, cc: 0, wheel: 0, holding: 0 },
  notional_value: 0,
  notional_change_pct: null,
  open_legs: 0,
  open_legs_breakdown: { puts: 0, calls: 0 },
  unrealized_pl: null,
  unrealized_pl_pct: null,
  // Empty cases per spec §14.3:
  // - largest_risk: null  → tile renders `—` with tooltip
  // - realized_pl/pct: 0  → tile renders `$0` / `0%` (NOT em-dash)
  // - premium: 0 / 0      → tile renders `$0` / `0 trades`
  largest_risk: null,
  premium_collected_total: 0,
  premium_collected_trades: 0,
  premium_collected_ytd: 0,
  realized_pl: 0,
  realized_pl_pct: null,
  largest_loser: null,
};

function mockDashboard(page, payload) {
  return page.route('**/api/dashboard', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(payload),
    })
  );
}

test.describe('KPI row (V0.5 — 7 tiles) @e2e', () => {
  test('renders all seven tiles when populated', async ({ page }) => {
    await mockDashboard(page, { ...BASE_PAYLOAD, kpis: POPULATED_KPIS });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const row = page.getByTestId('dashboard-kpi-row');
    await expect(row).toBeVisible();

    // Existing four tiles
    await expect(row.getByTestId('kpi-open-positions')).toBeVisible();
    await expect(row.getByTestId('kpi-notional')).toBeVisible();
    await expect(row.getByTestId('kpi-open-legs')).toBeVisible();
    await expect(row.getByTestId('kpi-unrealized-pl')).toBeVisible();

    // Three new tiles
    await expect(row.getByTestId('kpi-largest-risk')).toBeVisible();
    await expect(row.getByTestId('kpi-realized-pl')).toBeVisible();
    await expect(row.getByTestId('kpi-premium-lifetime')).toBeVisible();
  });

  test('Largest risk tile shows ticker, signed dollars, percent subtext, and tooltip', async ({ page }) => {
    await mockDashboard(page, { ...BASE_PAYLOAD, kpis: POPULATED_KPIS });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const tile = page.getByTestId('kpi-largest-risk');
    await expect(tile).toContainText('TSLA');
    await expect(tile).toContainText('-$1,420');
    await expect(tile).toContainText('-7.20% on basis');
    // Tooltip is rendered as a sibling element inside the tile
    await expect(tile).toContainText('Position with the largest unrealized loss.');
  });

  test('Realized P/L tile shows signed dollars and lifetime percent', async ({ page }) => {
    await mockDashboard(page, { ...BASE_PAYLOAD, kpis: POPULATED_KPIS });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const tile = page.getByTestId('kpi-realized-pl');
    await expect(tile).toContainText('+$1,932');
    await expect(tile).toContainText('+4.10% lifetime');
    await expect(tile).toContainText('Net P/L from closed positions and trades, lifetime.');
  });

  test('Premium tile shows signed total and trade count', async ({ page }) => {
    await mockDashboard(page, { ...BASE_PAYLOAD, kpis: POPULATED_KPIS });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const tile = page.getByTestId('kpi-premium-lifetime');
    await expect(tile).toContainText('+$2,847');
    await expect(tile).toContainText('38 trades');
  });

  test('empty Largest risk renders em-dash with tooltip', async ({ page }) => {
    await mockDashboard(page, {
      ...BASE_PAYLOAD,
      status: { ...BASE_PAYLOAD.status, journal: { positions_count: 0 } },
      kpis: EMPTY_KPIS,
    });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const tile = page.getByTestId('kpi-largest-risk');
    await expect(tile).toContainText('—');
    await expect(tile).toContainText('Position with the largest unrealized loss.');
  });

  test('empty Realized P/L renders $0 / 0% (zero-guard, not +$0.00, per spec §14.3)', async ({ page }) => {
    await mockDashboard(page, {
      ...BASE_PAYLOAD,
      status: { ...BASE_PAYLOAD.status, journal: { positions_count: 0 } },
      kpis: EMPTY_KPIS,
    });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const tile = page.getByTestId('kpi-realized-pl');
    await expect(tile).toContainText('$0');
    await expect(tile).not.toContainText('+$0.00');
    await expect(tile).toContainText('0% lifetime');
  });

  test('empty Premium renders $0 / 0 trades (zero-guard, not +$0.00, per spec §14.3)', async ({ page }) => {
    await mockDashboard(page, {
      ...BASE_PAYLOAD,
      status: { ...BASE_PAYLOAD.status, journal: { positions_count: 0 } },
      kpis: EMPTY_KPIS,
    });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const tile = page.getByTestId('kpi-premium-lifetime');
    await expect(tile).toContainText('$0');
    await expect(tile).not.toContainText('+$0.00');
    await expect(tile).toContainText('0 trades');
  });

  test('payload-only fields (premium_collected_ytd, largest_loser) do NOT render as tiles', async ({ page }) => {
    await mockDashboard(page, { ...BASE_PAYLOAD, kpis: POPULATED_KPIS });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    // No tile exposes premium_collected_ytd or largest_loser; only 7 tiles
    // total render. There is no `kpi-premium-ytd` or `kpi-largest-loser` id.
    await expect(page.getByTestId('kpi-premium-ytd')).toHaveCount(0);
    await expect(page.getByTestId('kpi-largest-loser')).toHaveCount(0);

    // largest_loser ticker (AMD) only appears in the payload; not on the row.
    const row = page.getByTestId('dashboard-kpi-row');
    await expect(row).not.toContainText('AMD');
  });

  test('renders 7 columns at desktop breakpoint (no horizontal scroll)', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await mockDashboard(page, { ...BASE_PAYLOAD, kpis: POPULATED_KPIS });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const row = page.getByTestId('dashboard-kpi-row');
    // The grid container uses lg:grid-cols-7 at lg+; assert via class presence
    // since runtime layout differs by browser default font sizes.
    await expect(row).toHaveClass(/lg:grid-cols-7/);

    // No horizontal scroll on the page body.
    const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
    expect(scrollWidth).toBeLessThanOrEqual(clientWidth + 1);
  });

  test('mobile (sm) uses 2-column grid; 7th tile spans 2 columns to avoid orphan', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await mockDashboard(page, { ...BASE_PAYLOAD, kpis: POPULATED_KPIS });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const row = page.getByTestId('dashboard-kpi-row');
    await expect(row).toHaveClass(/grid-cols-2/);

    // The premium tile wrapper carries the col-span-2 class on mobile.
    const premiumTile = page.getByTestId('kpi-premium-lifetime');
    const wrapperHandle = await premiumTile.evaluateHandle((el) => el.parentElement);
    const wrapperClass = await wrapperHandle.evaluate((el) => el.className);
    expect(wrapperClass).toContain('col-span-2');
  });
  test('signedCurrency zero-guard is symmetric: realized + premium use $0, unrealized stays +$0.00', async ({ page }) => {
    // Issue #172 spec §14.3 zero-guard applies to aggregate tiles only
    // (realized P/L + premium collected). Unrealized P/L is a current-state
    // pointer, not an aggregate, and intentionally retains the +$0.00 format
    // when value === 0. Guards against an accidental over-bleed of the fix.
    const zeroKpis = {
      ...EMPTY_KPIS,
      unrealized_pl: 0,
      unrealized_pl_pct: 0,
    };
    await mockDashboard(page, {
      ...BASE_PAYLOAD,
      status: { ...BASE_PAYLOAD.status, journal: { positions_count: 0 } },
      kpis: zeroKpis,
    });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    // Aggregate tiles: zero-guarded
    const realized = page.getByTestId('kpi-realized-pl');
    await expect(realized).toContainText('$0');
    await expect(realized).not.toContainText('+$0.00');

    const premium = page.getByTestId('kpi-premium-lifetime');
    await expect(premium).toContainText('$0');
    await expect(premium).not.toContainText('+$0.00');

    // Pointer tile: unchanged (+$0.00 is fine for unrealized at zero)
    const unrealized = page.getByTestId('kpi-unrealized-pl');
    await expect(unrealized).toContainText('+$0.00');
  });

});
