import { test, expect } from '@playwright/test';

/**
 * E2E for issue #247 — combined covered-call P&L + if-assigned projection.
 *
 * Covers the issue's AC:
 *   - The new route /positions/[id]/covered-call renders the populated view
 *     for a canonical covered call (the F worked example).
 *   - Today hero shows +$17.63; if-assigned hero shows +$217.34.
 *   - CSP-only / no-shares position renders the no-shares EmptyState.
 *   - A position with shares but no open short call renders the
 *     no-short-call EmptyState.
 *   - Closed position renders the closed EmptyState.
 *   - Degraded path — no live mid — renders today as em-dash and if-assigned
 *     normally.
 *   - Multi-leg variant renders one stacked block per leg in the if-assigned
 *     card, with the earliest-expiring leg holding the full shares_called.
 *   - Per-leg breakdown rows are not interactive (no href, no chevron — Q3).
 *   - The mandatory footer disclaimer is present.
 *   - The dashboard secondary `Covered call view →` link appears on CC /
 *     Wheel rows with shares > 0 and only on those rows; clicking it
 *     navigates to the new route.
 *
 * Every test mocks the covered-call endpoint at the route level — no live
 * backend or Schwab quote required.
 */

const POSITION_ID = 'pos-ford';
const COVERED_CALL_ROUTE = `/positions/${POSITION_ID}/covered-call`;

const DISCLAIMER =
  'These figures report the position state; they do not recommend an action. Roll / hold / let-assign decisions remain with you.';

// --- Fixture builders ------------------------------------------------------

function populatedPayload(overrides = {}) {
  return {
    position: {
      id: POSITION_ID,
      ticker: 'F',
      shares: 100,
      broker_cost_basis: 13.21,
      current_price: 13.1579,
      current_price_stale: false,
      current_price_as_of: '2026-05-19T18:31:00+00:00',
      ...overrides.position,
    },
    combined_today: {
      stock_pnl: -5.21,
      options_pnl: 22.84,
      combined_pnl: 17.63,
      ...overrides.combined_today,
    },
    if_assigned: overrides.if_assigned || [
      {
        leg_id: 'leg-ford-15c',
        strike: 15.0,
        premium: 0.3834,
        qty: 1,
        shares_called: 100,
        share_pnl: 179.00,
        premium_kept: 38.34,
        if_assigned_pnl: 217.34,
      },
    ],
    per_leg_breakdown: overrides.per_leg_breakdown || [
      {
        leg_id: 'leg-ford-15c',
        ticker: 'F',
        strike: 15.0,
        type: 'call',
        dte: 38,
        coverage: 'covered',
        pnl_dollars: 22.84,
        if_assigned_pnl: 217.34,
      },
    ],
    applicability: 'covered_call',
    disclaimer: DISCLAIMER,
  };
}

function emptyPayload(applicability, overrides = {}) {
  return {
    position: {
      id: POSITION_ID,
      ticker: 'F',
      shares: overrides.shares ?? 0,
      broker_cost_basis: overrides.basis ?? 13.21,
      current_price: null,
      current_price_stale: false,
      current_price_as_of: null,
    },
    combined_today: {
      stock_pnl: null,
      options_pnl: null,
      combined_pnl: null,
    },
    if_assigned: [],
    per_leg_breakdown: [],
    applicability,
    disclaimer: DISCLAIMER,
  };
}

function degradedNoMidPayload() {
  return populatedPayload({
    combined_today: {
      stock_pnl: -5.21,
      options_pnl: null,
      combined_pnl: null,
    },
    per_leg_breakdown: [
      {
        leg_id: 'leg-ford-15c',
        ticker: 'F',
        strike: 15.0,
        type: 'call',
        dte: 38,
        coverage: 'covered',
        pnl_dollars: null,
        if_assigned_pnl: 217.34,
      },
    ],
  });
}

function multiLegPayload() {
  return populatedPayload({
    if_assigned: [
      {
        leg_id: 'leg-A',
        strike: 15.0,
        premium: 0.3834,
        qty: 1,
        shares_called: 100,
        share_pnl: 179.00,
        premium_kept: 38.34,
        if_assigned_pnl: 217.34,
      },
      {
        leg_id: 'leg-B',
        strike: 16.0,
        premium: 0.25,
        qty: 1,
        shares_called: 0,
        share_pnl: 0.0,
        premium_kept: 25.00,
        if_assigned_pnl: 25.00,
      },
    ],
    per_leg_breakdown: [
      {
        leg_id: 'leg-A',
        ticker: 'F',
        strike: 15.0,
        type: 'call',
        dte: 38,
        coverage: 'covered',
        pnl_dollars: 22.84,
        if_assigned_pnl: 217.34,
      },
      {
        leg_id: 'leg-B',
        ticker: 'F',
        strike: 16.0,
        type: 'call',
        dte: 60,
        coverage: 'covered',
        pnl_dollars: 5.0,
        if_assigned_pnl: 25.00,
      },
    ],
    combined_today: {
      stock_pnl: -5.21,
      options_pnl: 27.84,
      combined_pnl: 22.63,
    },
  });
}

// --- Route mocks -----------------------------------------------------------

function mockCoveredCall(page, payload, status = 200) {
  return page.route(`**/api/positions/${POSITION_ID}/covered-call`, (route) =>
    route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(payload),
    }),
  );
}

async function openCoveredCall(page, route = COVERED_CALL_ROUTE) {
  await page.goto(route);
  await page.waitForLoadState('networkidle');
}

// --- Tests: route renders + populated view ---------------------------------

test.describe('Covered-call screen — route + populated view', () => {
  test('loads and renders combined P&L and if-assigned for the canonical F covered call', async ({
    page,
  }) => {
    await mockCoveredCall(page, populatedPayload());
    await openCoveredCall(page);

    await expect(page.getByTestId('covered-call-page')).toBeVisible();
    await expect(
      page.getByTestId('covered-call-position-header'),
    ).toContainText('Combined P&L: F');
    // Today hero — +$17.63 emerald.
    const todayHero = page.getByTestId('covered-call-today-hero');
    await expect(todayHero).toHaveAttribute('data-pnl-sign', 'gain');
    await expect(todayHero).toContainText('+$17.63');
    // If-assigned hero — +$217.34 (worked-example reconciliation choice).
    const ifaHero = page.getByTestId('covered-call-if-assigned-hero');
    await expect(ifaHero).toHaveAttribute('data-pnl-sign', 'gain');
    await expect(ifaHero).toContainText('+$217.34');
  });

  test('today card breakdown lines render stock + option + combined', async ({
    page,
  }) => {
    await mockCoveredCall(page, populatedPayload());
    await openCoveredCall(page);

    const breakdown = page.getByTestId('covered-call-today-breakdown');
    await expect(breakdown).toContainText('Stock leg');
    await expect(breakdown).toContainText('-$5.21');
    await expect(breakdown).toContainText('Option legs');
    await expect(breakdown).toContainText('+$22.84');
    await expect(breakdown).toContainText('Combined');
  });

  test('formula block and footer disclaimer render with exact spec copy', async ({
    page,
  }) => {
    await mockCoveredCall(page, populatedPayload());
    await openCoveredCall(page);

    await expect(page.getByTestId('covered-call-formulas')).toContainText(
      'Stock leg P&L = shares',
    );
    await expect(page.getByTestId('covered-call-formulas')).toContainText(
      'If-assigned = (strike',
    );
    // Disclaimer text verbatim — house framing rule (spec §3.6, §11).
    await expect(page.getByTestId('covered-call-disclaimer')).toContainText(
      'report the position state',
    );
    await expect(page.getByTestId('covered-call-disclaimer')).toContainText(
      'remain with you',
    );
  });

  test('per-leg breakdown rows are not interactive (read-only — Q3)', async ({
    page,
  }) => {
    await mockCoveredCall(page, populatedPayload());
    await openCoveredCall(page);

    const row = page.getByTestId('covered-call-leg-row');
    await expect(row).toBeVisible();
    // The row is a <tr> — no <a>/<button> wrapping it, no href.
    await expect(row).toHaveAttribute('data-leg-id', 'leg-ford-15c');
    const rowTag = await row.evaluate((el) => el.tagName.toLowerCase());
    expect(rowTag).toBe('tr');
    // No anchor child inside the row.
    const anchorCount = await row.locator('a').count();
    expect(anchorCount).toBe(0);
  });
});

// --- Tests: empty states ----------------------------------------------------

test.describe('Covered-call screen — empty states', () => {
  test('CSP-only renders covered-call-empty-no-shares', async ({ page }) => {
    await mockCoveredCall(page, emptyPayload('not_applicable_no_shares'));
    await openCoveredCall(page);

    await expect(
      page.getByTestId('covered-call-empty-no-shares'),
    ).toBeVisible();
    await expect(
      page.getByTestId('covered-call-empty-no-shares'),
    ).toContainText('not applicable');
    // The populated view's hero cards are NOT rendered for an empty state.
    await expect(page.getByTestId('covered-call-today-card')).toHaveCount(0);
  });

  test('holding with no short call renders covered-call-empty-no-short-call', async ({
    page,
  }) => {
    await mockCoveredCall(
      page,
      emptyPayload('not_applicable_no_short_call', { shares: 100 }),
    );
    await openCoveredCall(page);

    await expect(
      page.getByTestId('covered-call-empty-no-short-call'),
    ).toBeVisible();
    await expect(
      page.getByTestId('covered-call-empty-no-short-call'),
    ).toContainText('No open short call');
  });

  test('closed position renders covered-call-empty-closed', async ({
    page,
  }) => {
    await mockCoveredCall(
      page,
      emptyPayload('not_applicable_closed', { shares: 100 }),
    );
    await openCoveredCall(page);

    await expect(
      page.getByTestId('covered-call-empty-closed'),
    ).toBeVisible();
    await expect(
      page.getByTestId('covered-call-empty-closed'),
    ).toContainText('Position is closed');
  });
});

// --- Tests: degraded + multi-leg --------------------------------------------

test.describe('Covered-call screen — degraded + multi-leg', () => {
  test('degraded — no live mid — today hero shows em-dash, if-assigned renders normally', async ({
    page,
  }) => {
    await mockCoveredCall(page, degradedNoMidPayload());
    await openCoveredCall(page);

    const todayHero = page.getByTestId('covered-call-today-hero');
    await expect(todayHero).toHaveAttribute('data-pnl-sign', 'none');
    await expect(todayHero).toContainText('—');
    // If-assigned survives the degraded path — its math is feed-independent.
    const ifaHero = page.getByTestId('covered-call-if-assigned-hero');
    await expect(ifaHero).toContainText('+$217.34');
  });

  test('multi-leg renders one stacked block per leg with data-leg-id', async ({
    page,
  }) => {
    await mockCoveredCall(page, multiLegPayload());
    await openCoveredCall(page);

    // Both per-leg if-assigned blocks render.
    await expect(
      page.getByTestId('covered-call-if-assigned-leg-leg-A'),
    ).toBeVisible();
    await expect(
      page.getByTestId('covered-call-if-assigned-leg-leg-B'),
    ).toBeVisible();
    // Both per-leg breakdown rows render.
    await expect(
      page.locator('[data-testid="covered-call-leg-row"]'),
    ).toHaveCount(2);
    // Hero is the sum of the per-leg projections (217.34 + 25.00 = 242.34).
    await expect(
      page.getByTestId('covered-call-if-assigned-hero'),
    ).toContainText('+$242.34');
  });
});

// --- Tests: dashboard secondary link ---------------------------------------

const DASHBOARD_BASE = {
  generated_at: '2026-05-19T13:42:00+00:00',
  status: {
    schwab: { configured: true, valid: true, expires_at: '2026-08-01T00:00:00+00:00' },
    fred: { configured: true, valid: true },
    cache: { fresh: 12, stale: 0, very_stale: 0, total: 12 },
    journal: { positions_count: 1 },
  },
  kpis: {
    open_positions: 4,
    open_positions_breakdown: { stock: 1, csp: 1, cc: 1, wheel: 1, holding: 0 },
    notional_value: 4000,
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
      id: 'pos-cc',
      ticker: 'F',
      shares: 100,
      broker_cost_basis: 1321.0,
      adjusted_cost_basis: 1283.0,
      current_price: 13.15,
      pl_pct: -0.01,
      unrealized_pl: -10,
      wheel_status: 'CC',
      next_suggested_action: 'hold',
    },
    {
      id: 'pos-wheel',
      ticker: 'AAPL',
      shares: 100,
      broker_cost_basis: 15000.0,
      adjusted_cost_basis: 14900.0,
      current_price: 150.0,
      pl_pct: 0.0,
      unrealized_pl: 0,
      wheel_status: 'Wheel',
      next_suggested_action: 'hold',
    },
    {
      id: 'pos-csp',
      ticker: 'NVDA',
      shares: 0,
      broker_cost_basis: null,
      adjusted_cost_basis: null,
      current_price: null,
      pl_pct: null,
      unrealized_pl: null,
      wheel_status: 'CSP',
      next_suggested_action: 'hold',
    },
    {
      id: 'pos-holding',
      ticker: 'TSLA',
      shares: 50,
      broker_cost_basis: 10000.0,
      adjusted_cost_basis: 10000.0,
      current_price: 200.0,
      pl_pct: 0.0,
      unrealized_pl: 0,
      wheel_status: 'Holding',
      next_suggested_action: 'hold',
    },
  ],
  upcoming_expirations: [],
  open_legs: [],
  recent_activity: [],
  data_meta: {
    is_stale: false,
    fetched_at: '2026-05-19T13:42:00+00:00',
    sources_unavailable: [],
  },
  next_actions: [],
};

function mockDashboard(page) {
  return page.route('**/api/dashboard', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(DASHBOARD_BASE),
    }),
  );
}

test.describe('Dashboard — Covered call view → link visibility', () => {
  test('Covered call view → link appears on CC and Wheel rows; absent on CSP and Holding', async ({
    page,
  }) => {
    await mockDashboard(page);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    // The secondary link renders for the CC and Wheel rows.
    const links = page.locator(
      '[data-testid="dashboard-position-covered-call-link"]',
    );
    await expect(links).toHaveCount(2);
    // CC row carries the link to /positions/pos-cc/covered-call.
    await expect(links.first()).toHaveAttribute(
      'href',
      '/positions/pos-cc/covered-call',
    );
    await expect(links.nth(1)).toHaveAttribute(
      'href',
      '/positions/pos-wheel/covered-call',
    );
  });

  test('clicking the dashboard link navigates to /positions/{id}/covered-call', async ({
    page,
  }) => {
    await mockDashboard(page);
    await page.route(
      '**/api/positions/pos-cc/covered-call',
      (route) =>
        route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            ...populatedPayload(),
            position: { ...populatedPayload().position, id: 'pos-cc' },
          }),
        }),
    );
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const link = page
      .locator('[data-testid="dashboard-position-covered-call-link"]')
      .first();
    await link.click();
    await page.waitForLoadState('networkidle');

    await expect(page).toHaveURL(/\/positions\/pos-cc\/covered-call$/);
    await expect(page.getByTestId('covered-call-page')).toBeVisible();
  });
});
