import { test, expect } from '@playwright/test';

/**
 * E2E for issue #417 (PRD #415 R5) — honest quote freshness.
 *
 * Covers AC: the freshness pill is driven by the OLDEST displayed quote (amber
 * "Quotes stale (N)" when any shown quote exceeds the budget, red "very stale"
 * past the wider budget, green "Quotes fresh" otherwise), and each price cell
 * shows a per-symbol quote-age flag (muted when fresh, amber "⚠" when stale).
 */

const BASE_STATUS = {
  schwab: { configured: true, valid: true, expires_at: '2026-09-01T00:00:00+00:00' },
  fred: { configured: true, valid: true },
  // Research/data cache buckets are all fresh — the pill must NOT read from
  // these; it reads the displayed-quote signal below (the #417 bug fix).
  cache: {
    fresh: 12,
    stale: 0,
    very_stale: 0,
    total: 12,
    displayed_total: 2,
    displayed_stale: 1,
    stalest_symbol: 'BB',
    stalest_age_seconds: 1800, // 30m — amber "stale", below the 60m very-stale budget
  },
  journal: { positions_count: 2 },
};

const BASE_KPIS = {
  open_positions: 2,
  open_positions_breakdown: { stock: 0, csp: 0, cc: 0, wheel: 0, holding: 2 },
  notional_value: 2000,
  notional_change_pct: 0.01,
  open_legs: 0,
  open_legs_breakdown: { puts: 0, calls: 0 },
  unrealized_pl: 50,
  unrealized_pl_pct: 0.005,
  largest_risk: null,
  premium_collected_total: 0,
  premium_collected_trades: 0,
  premium_collected_ytd: 0,
  realized_pl: 0,
  realized_pl_pct: null,
  largest_loser: null,
};

const FRESH_ROW = {
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
  day_change: null,
  day_change_pct: null,
  day_state: 'no_prior_close',
  // R5 — fresh (2 minutes).
  quote_age_seconds: 120,
  quote_stale: false,
  quote_fetched_at: '2026-07-08T17:58:00+00:00',
};

const STALE_ROW = {
  id: 'pos-bb',
  ticker: 'BB',
  shares: 100,
  strategy: 'holding',
  adjusted_cost_basis: 500.0,
  broker_cost_basis: 500.0,
  adjusted_cost_basis_per_share: 5.0,
  broker_cost_basis_per_share: 5.0,
  current_price: 4.2,
  notional: 420.0,
  unrealized_pl: -80.0,
  pl_pct: -0.16,
  open_legs_count: 0,
  wheel_status: 'Holding',
  next_suggested_action: 'hold',
  day_change: null,
  day_change_pct: null,
  day_state: 'no_prior_close',
  // R5 — stale (30 minutes) — amber "stale" bucket, below the 60m very-stale budget.
  quote_age_seconds: 1800,
  quote_stale: true,
  quote_fetched_at: '2026-07-08T17:30:00+00:00',
};

function makePayload(overrides = {}) {
  return {
    generated_at: '2026-07-08T18:00:00+00:00',
    status: BASE_STATUS,
    kpis: BASE_KPIS,
    positions: [FRESH_ROW, STALE_ROW],
    open_legs: [],
    recent_activity: [],
    data_meta: {
      is_stale: false,
      fetched_at: '2026-07-08T18:00:00+00:00',
      sources_unavailable: [],
    },
    next_actions: [],
    account_summary: {
      account_value: null,
      equity_mv: null,
      option_mv: null,
      cash: null,
      day_change: null,
      day_change_pct: null,
      day_state: 'no_prior_close',
      reconciles: false,
    },
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

test.describe('Dashboard quote freshness @smoke @e2e', () => {
  test('freshness pill goes amber when a displayed quote is stale', async ({
    page,
  }) => {
    await mockDashboard(page, makePayload());
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const pill = page.getByTestId('status-pill-cache');
    await expect(pill).toBeVisible();
    await expect(pill).toHaveAttribute('data-freshness-state', 'stale');
    await expect(pill).toContainText('Quotes stale (1)');
    // Hover detail names the stalest symbol + budget.
    await expect(pill).toHaveAttribute('title', /Stalest quote: BB/);
  });

  test('per-symbol quote-age flag is amber on the stale row, muted on the fresh row', async ({
    page,
  }) => {
    await mockDashboard(page, makePayload());
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const flags = page.getByTestId('dashboard-position-quote-age');
    // Rendered in payload order: NOK (fresh) first, BB (stale) second.
    const nok = flags.nth(0);
    await expect(nok).toHaveAttribute('data-stale', 'false');
    await expect(nok).toContainText('2m');

    const bb = flags.nth(1);
    await expect(bb).toHaveAttribute('data-stale', 'true');
    await expect(bb).toContainText('30m');
    await expect(bb).toContainText('⚠');
  });

  test('freshness pill reads green when every displayed quote is fresh', async ({
    page,
  }) => {
    const payload = makePayload({
      positions: [FRESH_ROW],
      status: {
        ...BASE_STATUS,
        cache: {
          ...BASE_STATUS.cache,
          displayed_total: 1,
          displayed_stale: 0,
          stalest_symbol: 'NOK',
          stalest_age_seconds: 120,
        },
      },
    });
    await mockDashboard(page, payload);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const pill = page.getByTestId('status-pill-cache');
    await expect(pill).toHaveAttribute('data-freshness-state', 'fresh');
    await expect(pill).toContainText('Quotes fresh');
  });

  test('freshness pill goes red when the stalest quote is very stale', async ({
    page,
  }) => {
    const payload = makePayload({
      status: {
        ...BASE_STATUS,
        cache: {
          ...BASE_STATUS.cache,
          stalest_age_seconds: 4 * 3600, // 4h — past the very-stale budget
        },
      },
    });
    await mockDashboard(page, payload);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const pill = page.getByTestId('status-pill-cache');
    await expect(pill).toHaveAttribute('data-freshness-state', 'very_stale');
    await expect(pill).toContainText('Quotes very stale (1)');
  });
});
