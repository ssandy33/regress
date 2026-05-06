import { test, expect } from '@playwright/test';

/**
 * Asserts the rendered relative-time output for dashboard activity rows
 * matches `formatRelativeTime` semantics:
 *  - same day  → HH:MM
 *  - yesterday → "yest"
 *  - older     → "Mon D"
 *
 * Plan §10 risk #7 — guards against an off-by-one local-vs-UTC bug that
 * would render today's events as "yest" or as a date string.
 */

function buildPayloadWithActivityAt(iso, opts = {}) {
  const { kind = 'trade_added' } = opts;
  const event =
    kind === 'session_saved'
      ? {
          kind: 'session_saved',
          timestamp: iso,
          session_name: 'Time-format probe',
          session_id: 'sess-probe',
        }
      : {
          kind: 'trade_added',
          timestamp: iso,
          ticker: 'AAPL',
          trade_type: 'sell_put',
          position_id: 'pos-probe',
        };

  return {
    generated_at: new Date().toISOString(),
    status: {
      schwab: { configured: false, valid: false, expires_at: null },
      fred: { configured: false, valid: false },
      cache: { fresh: 0, stale: 0, very_stale: 0, total: 0 },
      journal: { positions_count: 1 },
    },
    kpis: {
      open_positions: 1,
      open_positions_breakdown: { stock: 0, csp: 0, cc: 0, wheel: 1 },
      notional_value: 0,
      notional_change_pct: null,
      open_legs: 0,
      open_legs_breakdown: { puts: 0, calls: 0 },
      unrealized_pl: null,
      unrealized_pl_pct: null,
    },
    positions: [
      {
        id: 'pos-probe',
        ticker: 'AAPL',
        shares: 100,
        strategy: 'wheel',
        adjusted_cost_basis: 17000.0,
        current_price: null,
        notional: null,
        unrealized_pl: null,
        open_legs_count: 0,
      },
    ],
    open_legs: [],
    upcoming_expirations: [],
    recent_activity: [event],
    data_meta: {
      is_stale: false,
      fetched_at: new Date().toISOString(),
      sources_unavailable: [],
    },
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

test.describe('Dashboard activity timestamp formatting', () => {
  test('a UTC timestamp from 2 hours ago renders as HH:MM (today), not "yest" or a date', async ({
    page,
  }) => {
    const twoHoursAgo = new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString();
    await mockDashboard(page, buildPayloadWithActivityAt(twoHoursAgo));

    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const row = page.getByTestId('dashboard-activity-row').first();
    await expect(row).toBeVisible();

    // The first child span holds the formatted timestamp (see RecentActivityCard).
    const stamp = (await row.locator('span').first().innerText()).trim();

    // Today → HH:MM (24h, zero-padded).
    expect(stamp).toMatch(/^\d{2}:\d{2}$/);
    // Definitely not the "yesterday" or "older date" branches.
    expect(stamp).not.toBe('yest');
    expect(stamp).not.toMatch(/^[A-Z][a-z]{2} \d{1,2}$/);
  });

  test('a timestamp from yesterday at local noon renders as "yest"', async ({
    page,
  }) => {
    // First, open a blank page so we can evaluate JS in the browser to build
    // "yesterday at local noon" in *the browser's* timezone (independent of
    // the test runner). Anchoring on local noon keeps us clear of midnight
    // rollover.
    await page.goto('about:blank');
    const yesterdayLocalNoonIso = await page.evaluate(() => {
      const d = new Date();
      d.setDate(d.getDate() - 1);
      d.setHours(12, 0, 0, 0);
      return d.toISOString();
    });
    await mockDashboard(page, buildPayloadWithActivityAt(yesterdayLocalNoonIso));

    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const row = page.getByTestId('dashboard-activity-row').first();
    await expect(row).toBeVisible();

    const stamp = (await row.locator('span').first().innerText()).trim();
    expect(stamp).toBe('yest');
  });
});
