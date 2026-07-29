import { test, expect } from '@playwright/test';

/**
 * E2E for #437 — the journal count on the dashboard status strip is an
 * INFORMATIONAL tally, not a health signal.
 *
 * Regression guard: a grey status dot sitting in a row of green health pills
 * (Schwab / FRED / Quotes) reads as "journal degraded." The journal item must
 * instead render a numeric count badge (variant="count") carrying the number,
 * with descriptive copy, and still link to /journal.
 */

const BASE_PAYLOAD = {
  generated_at: '2026-07-04T13:42:00+00:00',
  status: {
    schwab: { configured: true, valid: true, expires_at: '2026-09-01T00:00:00+00:00' },
    fred: { configured: true, valid: true },
    cache: { fresh: 12, stale: 0, very_stale: 0, total: 12 },
    journal: { positions_count: 4 },
  },
  positions: [],
  open_legs: [],
  recent_activity: [],
  data_meta: {
    is_stale: false,
    fetched_at: '2026-07-04T13:42:00+00:00',
    sources_unavailable: [],
  },
  account_summary: {
    account_value: 10526.76,
    equity_mv: 9166.0,
    option_mv: -4.5,
    cash: 1365.26,
    day_change: null,
    day_change_pct: null,
    day_state: 'no_prior_close',
    reconciles: true,
    reconcile_state: 'reconciled',
  },
  kpis: {
    open_positions: 0,
    open_positions_breakdown: { stock: 0, csp: 0, cc: 0, wheel: 0, holding: 0 },
    notional_value: 0,
    notional_change_pct: 0.0,
    open_legs: 0,
    open_legs_breakdown: { puts: 0, calls: 0 },
    unrealized_pl: 0,
    unrealized_pl_pct: 0,
    includes_options: false,
    largest_risk: null,
    premium_collected_total: 0,
    premium_collected_trades: 0,
    premium_collected_ytd: 0,
    realized_pl: 0,
    realized_pl_pct: null,
    largest_loser: null,
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

test.describe('Dashboard journal count pill (#437) @e2e', () => {
  test('journal count renders as a count badge with descriptive copy and links to /journal', async ({
    page,
  }) => {
    await mockDashboard(page, BASE_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const journal = page.getByTestId('status-pill-journal');
    await expect(journal).toBeVisible();

    // The tally is an exact numeric badge child — the count itself, not a
    // color dot that happens to sit beside a new label.
    await expect(journal.locator('span').filter({ hasText: /^4$/ })).toHaveCount(1);
    // It is NOT a health pill: health dots are aria-hidden color spans; the
    // count variant carries no such dot.
    await expect(journal.locator('span[aria-hidden="true"]')).toHaveCount(0);
    await expect(journal).toContainText('positions in Journal');
    // Descriptive hover names it as a journal tally, not a status.
    await expect(journal).toHaveAttribute('title', '4 open positions in your journal');

    // Navigational: the count links to the journal.
    await expect(journal).toHaveAttribute('href', '/journal');

    // Contrast: the real health pills DO carry an aria-hidden color dot.
    await expect(
      page.getByTestId('status-pill-schwab').locator('span[aria-hidden="true"]')
    ).toHaveCount(1);
  });

  test('singular copy when exactly one journaled position', async ({ page }) => {
    await mockDashboard(page, {
      ...BASE_PAYLOAD,
      status: { ...BASE_PAYLOAD.status, journal: { positions_count: 1 } },
    });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const journal = page.getByTestId('status-pill-journal');
    await expect(journal.locator('span').filter({ hasText: /^1$/ })).toHaveCount(1);
    await expect(journal).toContainText('position in Journal');
    await expect(journal).not.toContainText('positions in Journal');
    await expect(journal).toHaveAttribute('title', '1 open position in your journal');
  });
});
