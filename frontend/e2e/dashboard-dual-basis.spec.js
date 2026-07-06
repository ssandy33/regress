import { test, expect } from '@playwright/test';

/**
 * E2E for issue #422 (PRD #415 R6 / ADR #416 Option B) — dual-basis P&L.
 *
 * Covers AC:
 * - Every P&L cell renders two lines: the adjusted headline (colored) on line 1
 *   and the raw broker basis (muted, "raw" tag) on line 2.
 * - Raw-null rows (CSP/0-share) render a muted em-dash on the secondary line.
 * - The P0 review card fires on the RAW drawdown the adjusted basis hid, carries
 *   data-trigger-basis="raw", and shows a "fired on raw basis" tag.
 */

const BASE_STATUS = {
  schwab: { configured: true, valid: true, expires_at: '2026-09-01T00:00:00+00:00' },
  fred: { configured: true, valid: true },
  cache: { fresh: 12, stale: 0, very_stale: 0, total: 12 },
  journal: { positions_count: 2 },
};

const BASE_KPIS = {
  open_positions: 2,
  open_positions_breakdown: { stock: 0, csp: 1, cc: 0, wheel: 1, holding: 0 },
  notional_value: 4100,
  notional_change_pct: -0.02,
  open_legs: 1,
  open_legs_breakdown: { puts: 1, calls: 0 },
  unrealized_pl: -550,
  unrealized_pl_pct: -0.118,
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
    // SOFI — premium-softened: adjusted −$550 (−11.8%) headline, raw −$900 (−18%)
    // secondary. The raw drawdown is deeper than the adjusted headline.
    id: 'pos-sofi',
    ticker: 'SOFI',
    shares: 100,
    strategy: 'wheel',
    adjusted_cost_basis: 4650.0,
    broker_cost_basis: 5000.0,
    adjusted_cost_basis_per_share: 46.5,
    broker_cost_basis_per_share: 50.0,
    current_price: 41.0,
    notional: 4100.0,
    unrealized_pl: -550.0,
    pl_pct: -0.1183,
    raw_unrealized_pl: -900.0,
    raw_pl_pct: -0.18,
    open_legs_count: 0,
    wheel_status: 'Wheel',
    next_suggested_action: 'Review',
    day_change: -200.0,
    day_change_pct: -0.0465,
    day_state: 'populated',
  },
  {
    // CSP — no broker basis → raw secondary renders a muted em-dash.
    id: 'pos-csp',
    ticker: 'PLTR',
    shares: 0,
    strategy: 'csp',
    adjusted_cost_basis: 0.0,
    broker_cost_basis: null,
    adjusted_cost_basis_per_share: null,
    broker_cost_basis_per_share: null,
    current_price: 42.0,
    notional: null,
    unrealized_pl: null,
    pl_pct: null,
    raw_unrealized_pl: null,
    raw_pl_pct: null,
    open_legs_count: 1,
    wheel_status: 'CSP',
    next_suggested_action: 'hold',
    day_change: null,
    day_change_pct: null,
    day_state: 'no_prior_close',
  },
];

const NEXT_ACTIONS = [
  {
    id: 'position.large_loser.pos-sofi',
    action_id: 'position.large_loser',
    priority: 'P0',
    title: 'Review SOFI',
    subject: { ticker: 'SOFI', amount: 'SOFI -$900 (-18.0%)' },
    trigger_basis: 'raw',
    reason:
      'Down -18.0% on raw broker basis (-11.8% adjusted). Below your -15% review threshold (or -$1,000 absolute).',
    cta: { label: 'Review SOFI', href: '/positions/pos-sofi/recovery', kind: 'link' },
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
  next_actions: NEXT_ACTIONS,
  account_summary: {
    account_value: null,
    equity_mv: null,
    option_mv: null,
    cash: null,
    day_change: -200.0,
    day_change_pct: -0.0465,
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

test.describe('Dashboard dual-basis P&L @e2e', () => {
  test('P&L cells stack adjusted headline over raw broker-basis secondary', async ({
    page,
  }) => {
    await mockDashboard(page, PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    // %P/L cell — line 1 adjusted −11.83% (colored), line 2 raw −18.00% ("raw").
    const pctAdj = page.getByTestId('dashboard-position-pl-pct').first();
    await expect(pctAdj).toContainText('-11.83%');
    const pctRaw = page.getByTestId('dashboard-position-pl-pct-raw').first();
    await expect(pctRaw).toContainText('-18.00%');
    await expect(pctRaw).toContainText('raw');

    // P/L $ cell — line 1 adjusted −$550, line 2 raw −$900 ("raw").
    const dollarAdj = page.getByTestId('dashboard-position-pl').first();
    await expect(dollarAdj).toContainText('-$550');
    const dollarRaw = page.getByTestId('dashboard-position-pl-raw').first();
    await expect(dollarRaw).toContainText('-$900');
    await expect(dollarRaw).toContainText('raw');
  });

  test('raw-null row renders a muted em-dash on the secondary line', async ({
    page,
  }) => {
    await mockDashboard(page, PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    // The CSP row (2nd) has no broker basis → raw %P/L line is an em-dash.
    const cspRaw = page.getByTestId('dashboard-position-pl-pct-raw').nth(1);
    await expect(cspRaw).toContainText('—');
  });

  test('P0 review card fires on raw basis with a fired-on-raw tag', async ({
    page,
  }) => {
    await mockDashboard(page, PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const card = page.getByTestId('next-actions-card-position.large_loser.pos-sofi');
    await expect(card).toBeVisible();
    await expect(card).toHaveAttribute('data-trigger-basis', 'raw');
    // Reads the raw −18% / −$900 figure, not the softer adjusted −11.8% / −$550.
    await expect(card).toContainText('-$900');
    await expect(card).toContainText('raw broker basis');
    await expect(card.getByTestId('next-actions-card-basis-tag')).toContainText(
      'fired on raw basis'
    );
  });
});
