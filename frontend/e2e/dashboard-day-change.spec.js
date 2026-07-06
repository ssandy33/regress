import { test, expect } from '@playwright/test';

/**
 * E2E for issue #421 (PRD #415 R3) — per-position + account-level day change.
 *
 * Covers AC: DAY column populated with signed $/% (green up / red down);
 * explicit "no prior close" state (data-day-state="no_prior_close"); the new
 * Account Summary strip renders the account-level day-change tile.
 */

const BASE_STATUS = {
  schwab: { configured: true, valid: true, expires_at: '2026-09-01T00:00:00+00:00' },
  fred: { configured: true, valid: true },
  cache: { fresh: 12, stale: 0, very_stale: 0, total: 12 },
  journal: { positions_count: 3 },
};

const BASE_KPIS = {
  open_positions: 3,
  open_positions_breakdown: { stock: 0, csp: 1, cc: 1, wheel: 1, holding: 0 },
  notional_value: 30000,
  notional_change_pct: 0.01,
  open_legs: 2,
  open_legs_breakdown: { puts: 1, calls: 1 },
  unrealized_pl: 150,
  unrealized_pl_pct: 0.005,
  largest_risk: null,
  premium_collected_total: 0,
  premium_collected_trades: 0,
  premium_collected_ytd: 0,
  realized_pl: 0,
  realized_pl_pct: null,
  largest_loser: null,
};

const POSITIONS = [
  {
    id: 'pos-nok',
    ticker: 'NOK',
    shares: 100,
    strategy: 'holding',
    adjusted_cost_basis: 1207.0,
    broker_cost_basis: 1207.0,
    adjusted_cost_basis_per_share: 12.07,
    broker_cost_basis_per_share: 12.07,
    current_price: 12.5,
    notional: 1250.0,
    unrealized_pl: 43.0,
    pl_pct: 0.0356,
    open_legs_count: 0,
    wheel_status: 'Holding',
    next_suggested_action: 'hold',
    // R3 — up day (green).
    day_change: 43.0,
    day_change_pct: 0.0356,
    day_state: 'populated',
  },
  {
    id: 'pos-sofi',
    ticker: 'SOFI',
    shares: 100,
    strategy: 'wheel',
    adjusted_cost_basis: 800.0,
    broker_cost_basis: 900.0,
    adjusted_cost_basis_per_share: 8.0,
    broker_cost_basis_per_share: 9.0,
    current_price: 7.5,
    notional: 750.0,
    unrealized_pl: -50.0,
    pl_pct: -0.0625,
    open_legs_count: 1,
    wheel_status: 'Wheel',
    next_suggested_action: 'hold',
    // R3 — down day (red).
    day_change: -30.0,
    day_change_pct: -0.038,
    day_state: 'populated',
  },
  {
    id: 'pos-csp',
    ticker: 'PLTR',
    shares: 0,
    strategy: 'csp',
    adjusted_cost_basis: 0.0,
    broker_cost_basis: null,
    adjusted_cost_basis_per_share: null,
    broker_cost_basis_per_share: null,
    current_price: null,
    notional: null,
    unrealized_pl: null,
    pl_pct: null,
    open_legs_count: 1,
    wheel_status: 'CSP',
    next_suggested_action: 'hold',
    // R3 — no prior close available.
    day_change: null,
    day_change_pct: null,
    day_state: 'no_prior_close',
  },
];

const PAYLOAD = {
  generated_at: '2026-07-06T13:42:00+00:00',
  status: BASE_STATUS,
  kpis: BASE_KPIS,
  positions: POSITIONS,
  open_legs: [],
  recent_activity: [],
  data_meta: {
    is_stale: false,
    fetched_at: '2026-07-06T13:42:00+00:00',
    sources_unavailable: [],
  },
  next_actions: [],
  account_summary: {
    account_value: null,
    equity_mv: null,
    option_mv: null,
    cash: null,
    day_change: 13.0,
    day_change_pct: 0.0065,
    day_state: 'populated',
    reconciles: false,
  },
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

test.describe('Dashboard day change @e2e', () => {
  test('per-position DAY cell renders signed $/% up (green) and down (red)', async ({
    page,
  }) => {
    await mockDashboard(page, PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const dayCells = page.getByTestId('dashboard-position-day');

    // NOK — up day, populated, green +$43.00 / +3.56%.
    const nok = dayCells.nth(0);
    await expect(nok).toHaveAttribute('data-day-state', 'populated');
    await expect(nok).toContainText('+$43.00');
    await expect(nok).toContainText('+3.56%');
    await expect(nok.locator('.text-green-600')).toBeVisible();

    // SOFI — down day, populated, red.
    const sofi = dayCells.nth(1);
    await expect(sofi).toHaveAttribute('data-day-state', 'populated');
    await expect(sofi).toContainText('-$30.00');
    await expect(sofi.locator('.text-red-600')).toBeVisible();
  });

  test('symbol with no prior close renders the explicit empty state', async ({
    page,
  }) => {
    await mockDashboard(page, PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const csp = page.getByTestId('dashboard-position-day').nth(2);
    await expect(csp).toHaveAttribute('data-day-state', 'no_prior_close');
    await expect(csp).toContainText('no prior close');
  });

  test('account summary strip renders the account-level day-change tile', async ({
    page,
  }) => {
    await mockDashboard(page, PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    await expect(page.getByTestId('dashboard-account-summary')).toBeVisible();

    const dayTile = page.getByTestId('kpi-day-change');
    await expect(dayTile).toHaveAttribute('data-day-state', 'populated');
    await expect(dayTile).toContainText('+$13.00');
    await expect(dayTile).toContainText('+0.65%');

    // Broker reconciliation not wired yet → account value tile is unavailable.
    const valueTile = page.getByTestId('kpi-account-value');
    await expect(valueTile).toHaveAttribute('data-reconciles', 'false');
    await expect(valueTile).toContainText('Connect Schwab to reconcile');
  });
});
