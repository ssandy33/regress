import { test, expect } from '@playwright/test';

/**
 * E2E for issue #248 — urgency-aware DTE pill + retired Upcoming-expirations
 * panel.
 *
 * Covers AC:
 *   - DTE pill is color-coded red ≤ 7 / amber ≤ 14 / neutral > 14, surfaced via
 *     the stable `data-dte-urgency="red|amber|neutral"` attribute on the
 *     `dashboard-leg-row-dte` testid.
 *   - Boundary semantics: equality flows to the more urgent tier
 *     (dte 7 → red, dte 14 → amber). Matches `compute_assignment_risk()`'s
 *     `<=` boundaries — the source of truth named in OpenLegsCard.jsx.
 *   - The retired Upcoming-expirations panel does not render on the dashboard
 *     under any branch.
 *   - The legs-card footer carries a reachable "Open Journal" link that
 *     navigates to `/journal`.
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
  recent_activity: [],
  data_meta: {
    is_stale: false,
    fetched_at: '2026-05-12T13:42:00+00:00',
    sources_unavailable: [],
  },
};

// A minimal four-row triggered_rules payload — enough for the InspectPanel
// to render. Mirrors the helper in dashboard-open-legs-card.spec.js.
function makeTriggeredRules() {
  return ['assignment_risk', 'expiration_warning', 'profit_review', 'dte_review'].map(
    (rule_id) => ({
      rule_id,
      metric_label: rule_id === 'profit_review' ? 'Premium captured' : 'Days to expiration',
      value_display: '—',
      rule_display: 'Review at ≥ 50%',
      status: 'no',
      is_governing: false,
      reasoning: null,
    })
  );
}

function makeLeg(overrides = {}) {
  return {
    id: 'leg-1',
    ticker: 'AAPL',
    type: 'put',
    strike: 175.0,
    expiration: '2026-05-19',
    dte: 7,
    moneyness: { state: 'OTM', distance_pct: 0.05, distance_dollars: 8.75 },
    position_id: 'pos-aapl',
    profit_target_status: { captured_pct: null, state: 'unknown' },
    assignment_risk: 'low',
    suggested_action: 'hold',
    earnings_in_window: false,
    verdict: 'hold',
    verdict_label: 'Hold',
    reasoning: 'No management rule has triggered for this leg yet.',
    triggered_rules: makeTriggeredRules(),
    coverage: null,
    premium: null,
    pnl_dollars: null,
    cost_to_close: null,
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

test.describe('OpenLegsCard — urgency-aware DTE pill (issue #248) @e2e', () => {
  test('dte 5 → red urgency tier', async ({ page }) => {
    const leg = makeLeg({ dte: 5 });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [leg] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const pill = page.getByTestId('dashboard-leg-row-dte').first();
    await expect(pill).toBeVisible();
    await expect(pill).toHaveAttribute('data-dte-urgency', 'red');
    await expect(pill).toContainText('5d');
  });

  test('dte 12 → amber urgency tier', async ({ page }) => {
    const leg = makeLeg({ dte: 12 });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [leg] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const pill = page.getByTestId('dashboard-leg-row-dte').first();
    await expect(pill).toHaveAttribute('data-dte-urgency', 'amber');
  });

  test('dte 38 → neutral urgency tier', async ({ page }) => {
    const leg = makeLeg({ dte: 38 });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [leg] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const pill = page.getByTestId('dashboard-leg-row-dte').first();
    await expect(pill).toHaveAttribute('data-dte-urgency', 'neutral');
  });

  // Boundary cases — pin the `<=` semantics. The frontend tier function and
  // the backend compute_assignment_risk() helper both use `<=`, so equality
  // flows to the more urgent tier on both sides. Drifting these is exactly
  // the failure mode the issue's "thresholds must match backend" AC catches.
  test('boundary: dte 7 → red (equality goes to red, not amber)', async ({ page }) => {
    const leg = makeLeg({ dte: 7 });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [leg] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const pill = page.getByTestId('dashboard-leg-row-dte').first();
    await expect(pill).toHaveAttribute('data-dte-urgency', 'red');
  });

  test('boundary: dte 8 → amber (one past the red threshold)', async ({ page }) => {
    const leg = makeLeg({ dte: 8 });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [leg] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const pill = page.getByTestId('dashboard-leg-row-dte').first();
    await expect(pill).toHaveAttribute('data-dte-urgency', 'amber');
  });

  test('boundary: dte 14 → amber (equality goes to amber, not neutral)', async ({ page }) => {
    const leg = makeLeg({ dte: 14 });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [leg] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const pill = page.getByTestId('dashboard-leg-row-dte').first();
    await expect(pill).toHaveAttribute('data-dte-urgency', 'amber');
  });

  test('boundary: dte 15 → neutral (one past the amber threshold)', async ({ page }) => {
    const leg = makeLeg({ dte: 15 });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [leg] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const pill = page.getByTestId('dashboard-leg-row-dte').first();
    await expect(pill).toHaveAttribute('data-dte-urgency', 'neutral');
  });

  test('the retired Upcoming-expirations panel is absent from the dashboard', async ({ page }) => {
    // Even on a populated dashboard with a near-expiry ITM leg (the exact
    // shape the retired panel used to highlight), the panel does not render.
    const nearItm = makeLeg({
      id: 'leg-near-itm',
      dte: 3,
      moneyness: { state: 'ITM', distance_pct: 0.0024, distance_dollars: 0.42 },
      assignment_risk: 'high',
    });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [nearItm] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    await expect(page.getByTestId('dashboard-expirations-card')).toHaveCount(0);
  });

  test('legs-card footer carries an "Open Journal" link to /journal', async ({ page }) => {
    const leg = makeLeg();
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [leg] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const journalLink = page.getByTestId('dashboard-legs-card-journal-link');
    await expect(journalLink).toBeVisible();
    await expect(journalLink).toHaveAttribute('href', '/journal');
    await expect(journalLink).toContainText('Open Journal');
  });
});
