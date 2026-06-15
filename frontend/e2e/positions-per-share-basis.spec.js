import { test, expect } from '@playwright/test';

/**
 * Issue #320 — per-share cost basis in the Positions table.
 *
 * Asserts the journal PositionsTable and the dashboard PositionsCard render
 * basis per share (with a "/sh" affordance) instead of totals, and that a
 * zero-shares row degrades gracefully (journal → em-dash; dashboard →
 * "cash-secured"). The dashboard cost-basis cell aligns 1:1 with the
 * per-share Current column — the whole point of the issue.
 */

// --- Journal PositionsTable -------------------------------------------------

const JOURNAL_POSITION = {
  id: 'pos-1',
  ticker: 'AAPL',
  shares: 100,
  broker_cost_basis: 15000.0,
  status: 'open',
  strategy: 'wheel',
  opened_at: '2025-01-15T10:00:00Z',
  closed_at: null,
  notes: null,
  total_premiums: 350.0,
  adjusted_cost_basis: 14650.0,
  broker_cost_basis_per_share: 150.0,
  adjusted_cost_basis_per_share: 146.5,
  min_compliant_cc_strike: 161.15,
  trades: [],
};

// Orphaned / closed-out row: zero shares → backend sends null per-share basis.
const ZERO_SHARE_POSITION = {
  id: 'pos-2',
  ticker: 'ZERO',
  shares: 0,
  broker_cost_basis: 0.0,
  status: 'closed',
  strategy: 'csp',
  opened_at: '2025-01-15T10:00:00Z',
  closed_at: '2025-02-15T10:00:00Z',
  notes: null,
  total_premiums: 0.0,
  adjusted_cost_basis: 0.0,
  broker_cost_basis_per_share: null,
  adjusted_cost_basis_per_share: null,
  min_compliant_cc_strike: 0.0,
  trades: [],
};

function mockJournal(page, positions) {
  return page.route('**/api/journal/positions', (route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ positions }),
      });
    }
    return route.continue();
  });
}

test.describe('Per-share cost basis — journal table @e2e', () => {
  test('broker + adjusted basis render per-share with /sh affordance @smoke', async ({
    page,
  }) => {
    await mockJournal(page, [JOURNAL_POSITION]);
    await page.goto('/journal');
    await page.waitForLoadState('networkidle');

    const broker = page.getByTestId('position-broker-basis-per-share').first();
    const adjusted = page
      .getByTestId('position-adjusted-basis-per-share')
      .first();

    // 15000 / 100 = $150.00; 14650 / 100 = $146.50.
    await expect(broker).toContainText('$150.00');
    await expect(broker).toContainText('/sh');
    await expect(adjusted).toContainText('$146.50');
    await expect(adjusted).toContainText('/sh');
  });

  test('zero-shares row renders em-dash, never $0.00 / Infinity', async ({
    page,
  }) => {
    await mockJournal(page, [ZERO_SHARE_POSITION]);
    await page.goto('/journal');
    await page.waitForLoadState('networkidle');

    const broker = page.getByTestId('position-broker-basis-per-share').first();
    const adjusted = page
      .getByTestId('position-adjusted-basis-per-share')
      .first();

    await expect(broker).toContainText('—');
    await expect(adjusted).toContainText('—');
    await expect(broker).not.toContainText('$');
    await expect(broker).not.toContainText('Infinity');
    await expect(adjusted).not.toContainText('$');
  });
});

// --- Dashboard PositionsCard ------------------------------------------------

const BASE_STATUS = {
  schwab: { configured: true, valid: true, expires_at: '2026-12-31T00:00:00Z' },
  fred: { configured: false },
};

const BASE_KPIS = {
  open_positions: 1,
  open_positions_breakdown: { csp: 0, cc: 0, wheel: 1, holding: 0 },
  total_premium_collected: 0,
  largest_risk: null,
  premium_collected_total: 0,
  premium_collected_trades: 0,
  premium_collected_ytd: 0,
  realized_pl: 0,
  realized_pl_pct: null,
  largest_loser: null,
};

const DASHBOARD_POSITION = {
  id: 'pos-aapl',
  ticker: 'AAPL',
  shares: 100,
  strategy: 'wheel',
  adjusted_cost_basis: 16983.0,
  broker_cost_basis: 17240.0,
  adjusted_cost_basis_per_share: 169.83,
  broker_cost_basis_per_share: 172.4,
  current_price: 175.42,
  notional: 17542.0,
  unrealized_pl: 559.0,
  pl_pct: 0.0329,
  open_legs_count: 1,
  wheel_status: 'Wheel',
  next_suggested_action: 'hold',
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

test.describe('Per-share cost basis — dashboard card @e2e', () => {
  test('basis cell renders per-share, aligned with the per-share Current column', async ({
    page,
  }) => {
    await mockDashboard(page, {
      generated_at: '2026-06-14T13:42:00+00:00',
      status: BASE_STATUS,
      kpis: BASE_KPIS,
      positions: [DASHBOARD_POSITION],
      open_legs: [],
      recent_activity: [],
      data_meta: {
        is_stale: false,
        fetched_at: '2026-06-14T13:42:00+00:00',
        sources_unavailable: [],
      },
      next_actions: [],
    });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const row = page.getByTestId('dashboard-position-row').first();
    const broker = row.getByTestId('dashboard-position-broker-basis');
    const adjusted = row.getByTestId('dashboard-position-adjusted-basis');

    // Per-share basis (172.40 / 169.83) reads against the per-share Current
    // price (175.42) in the adjacent column — no head-math required.
    await expect(broker).toContainText('$172.40');
    await expect(broker).toContainText('/sh');
    await expect(adjusted).toContainText('$169.83');
    await expect(adjusted).toContainText('/sh');
    await expect(adjusted).toContainText('adj.');
    await expect(row).toContainText('$175.42'); // Current column, per-share.
  });
});
