import { test, expect } from '@playwright/test';

/**
 * E2E for issue #114 — unified Dashboard.
 *
 * Mirrors the AC scenarios:
 * - default-route redirect (`/` → `/dashboard`)
 * - populated state (KPIs, expirations, positions, activity)
 * - empty state (onboarding panel)
 * - disconnected Schwab indicator (red status pill, em-dash placeholders)
 * - Analysis still reachable at `/analysis`
 * - Header has Dashboard + Analysis links
 */

const POPULATED_PAYLOAD = {
  generated_at: '2026-05-05T13:42:00+00:00',
  status: {
    schwab: { configured: true, valid: true, expires_at: '2026-05-12T00:00:00+00:00' },
    fred: { configured: true, valid: true },
    cache: { fresh: 12, stale: 0, very_stale: 0, total: 12 },
    journal: { positions_count: 3 },
  },
  kpis: {
    open_positions: 3,
    open_positions_breakdown: { stock: 2, csp: 0, cc: 0, wheel: 1 },
    notional_value: 48210.0,
    notional_change_pct: 0.021,
    open_legs: 3,
    open_legs_breakdown: { puts: 2, calls: 1 },
    unrealized_pl: 612.0,
    unrealized_pl_pct: 0.013,
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
    {
      id: 'pos-tsla',
      ticker: 'TSLA',
      shares: 50,
      strategy: 'cc',
      adjusted_cost_basis: 11755.0,
      current_price: 238.8,
      notional: 11940.0,
      unrealized_pl: 185.0,
      open_legs_count: 1,
    },
    {
      id: 'pos-nvda',
      ticker: 'NVDA',
      shares: 0,
      strategy: 'csp',
      adjusted_cost_basis: 0.0,
      current_price: null,
      notional: null,
      unrealized_pl: null,
      open_legs_count: 1,
    },
  ],
  open_legs: [
    {
      id: 'leg-1',
      ticker: 'AAPL',
      type: 'put',
      strike: 175.0,
      expiration: '2026-05-08',
      dte: 3,
      moneyness: { state: 'ITM', distance_pct: 0.0024, distance_dollars: 0.42 },
      position_id: 'pos-aapl',
    },
    {
      id: 'leg-2',
      ticker: 'TSLA',
      type: 'call',
      strike: 240.0,
      expiration: '2026-05-15',
      dte: 10,
      moneyness: { state: 'OTM', distance_pct: 0.041, distance_dollars: 1.2 },
      position_id: 'pos-tsla',
    },
    {
      id: 'leg-3',
      ticker: 'NVDA',
      type: 'put',
      strike: 920.0,
      expiration: '2026-05-22',
      dte: 17,
      moneyness: null,
      position_id: 'pos-nvda',
    },
  ],
  upcoming_expirations: [
    {
      id: 'leg-1',
      ticker: 'AAPL',
      type: 'put',
      strike: 175.0,
      expiration: '2026-05-08',
      dte: 3,
      moneyness: { state: 'ITM', distance_pct: 0.0024, distance_dollars: 0.42 },
      position_id: 'pos-aapl',
      decision_tag: 'roll-or-assign',
      decision_reason: 'ITM by $0.42',
    },
    {
      id: 'leg-2',
      ticker: 'TSLA',
      type: 'call',
      strike: 240.0,
      expiration: '2026-05-15',
      dte: 10,
      moneyness: { state: 'OTM', distance_pct: 0.041, distance_dollars: 1.2 },
      position_id: 'pos-tsla',
      decision_tag: 'hold',
      decision_reason: 'OTM 4.1%',
    },
  ],
  recent_activity: [
    {
      kind: 'trade_added',
      timestamp: '2026-05-05T09:42:00+00:00',
      ticker: 'AAPL',
      trade_type: 'sell_call',
      position_id: 'pos-aapl',
    },
    {
      kind: 'session_saved',
      timestamp: '2026-05-04T15:00:00+00:00',
      session_name: 'AAPL vs DGS10 5y',
      session_id: 'sess-1',
    },
  ],
  data_meta: {
    is_stale: false,
    fetched_at: '2026-05-05T13:42:00+00:00',
    sources_unavailable: [],
  },
};

const EMPTY_PAYLOAD = {
  generated_at: '2026-05-05T13:42:00+00:00',
  status: {
    schwab: { configured: false, valid: false, expires_at: null },
    fred: { configured: false, valid: false },
    cache: { fresh: 0, stale: 0, very_stale: 0, total: 0 },
    journal: { positions_count: 0 },
  },
  kpis: {
    open_positions: 0,
    open_positions_breakdown: { stock: 0, csp: 0, cc: 0, wheel: 0 },
    notional_value: 0,
    notional_change_pct: null,
    open_legs: 0,
    open_legs_breakdown: { puts: 0, calls: 0 },
    unrealized_pl: null,
    unrealized_pl_pct: null,
  },
  positions: [],
  open_legs: [],
  upcoming_expirations: [],
  recent_activity: [],
  data_meta: {
    is_stale: false,
    fetched_at: '2026-05-05T13:42:00+00:00',
    sources_unavailable: [],
  },
};

const DISCONNECTED_PAYLOAD = {
  ...POPULATED_PAYLOAD,
  status: {
    ...POPULATED_PAYLOAD.status,
    schwab: { configured: false, valid: false, expires_at: null },
  },
  positions: POPULATED_PAYLOAD.positions.map((p) => ({
    ...p,
    current_price: null,
    notional: null,
    unrealized_pl: null,
  })),
  kpis: {
    ...POPULATED_PAYLOAD.kpis,
    notional_value: 0,
    notional_change_pct: null,
    unrealized_pl: null,
    unrealized_pl_pct: null,
  },
  data_meta: {
    is_stale: true,
    fetched_at: '2026-05-05T13:42:00+00:00',
    sources_unavailable: ['schwab'],
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

test.describe('Dashboard route', () => {
  test('default route `/` redirects to /dashboard', async ({ page }) => {
    await mockDashboard(page, EMPTY_PAYLOAD);
    await page.goto('/');
    await page.waitForURL(/\/dashboard$/, { timeout: 10000 });
    expect(page.url()).toMatch(/\/dashboard$/);
  });

  test('renders populated state with KPIs, expirations, positions, activity', async ({ page }) => {
    await mockDashboard(page, POPULATED_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    await expect(page.getByTestId('dashboard-page')).toBeVisible();
    await expect(page.getByTestId('dashboard-status-strip')).toBeVisible();

    // Status pills
    await expect(page.getByTestId('status-pill-schwab')).toContainText('Schwab connected');
    await expect(page.getByTestId('status-pill-fred')).toContainText('FRED connected');

    // KPI row
    const kpis = page.getByTestId('dashboard-kpi-row');
    await expect(kpis.getByTestId('kpi-open-positions')).toContainText('3');
    await expect(kpis.getByTestId('kpi-open-legs')).toContainText('3');

    // Decision row — AAPL roll-or-assign
    const expirationCard = page.getByTestId('dashboard-expirations-card');
    await expect(expirationCard).toContainText('AAPL');
    await expect(expirationCard).toContainText('Roll or assign');

    // Positions table — 3 rows
    await expect(page.getByTestId('dashboard-position-row')).toHaveCount(3);

    // Recent activity — 2 entries
    await expect(page.getByTestId('dashboard-activity-row')).toHaveCount(2);
  });

  test('renders onboarding panel in empty state', async ({ page }) => {
    await mockDashboard(page, EMPTY_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    await expect(page.getByTestId('dashboard-onboarding')).toBeVisible();
    await expect(page.getByTestId('dashboard-onboarding')).toContainText('Welcome to Regress');

    // Decision row + KPIs are absent
    await expect(page.getByTestId('dashboard-expirations-card')).toHaveCount(0);
    await expect(page.getByTestId('dashboard-positions-card')).toHaveCount(0);
  });

  test('shows Schwab disconnected indicator and em-dash placeholders', async ({ page }) => {
    await mockDashboard(page, DISCONNECTED_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    await expect(page.getByTestId('status-pill-schwab')).toContainText('not connected');

    // KPI row's Notional should show em-dash (no current prices)
    await expect(page.getByTestId('kpi-notional')).toContainText('—');
    await expect(page.getByTestId('kpi-unrealized-pl')).toContainText('—');

    // Positions render but with em-dashes for current/notional/PL
    const firstRow = page.getByTestId('dashboard-position-row').first();
    await expect(firstRow).toContainText('—');
  });

  test('Analysis page is reachable at /analysis', async ({ page }) => {
    await page.goto('/analysis');
    await page.waitForLoadState('domcontentloaded');
    // The Analysis layout includes the Run Analysis button in the sidebar.
    await expect(page.getByRole('button', { name: /run analysis/i })).toBeVisible();
  });

  test('header has Dashboard and Analysis links', async ({ page }) => {
    await mockDashboard(page, EMPTY_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const header = page.locator('header');
    await expect(header.getByRole('link', { name: 'Dashboard', exact: true })).toBeVisible();
    await expect(header.getByRole('link', { name: 'Analysis', exact: true })).toBeVisible();
  });
});
