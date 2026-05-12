import { test, expect } from '@playwright/test';

/**
 * E2E for issue #153 — Recent Activity refactor.
 *
 * Covers AC: filter chips (All / Trades / Sessions / Imports), single-active
 * semantics, ticker search (case-insensitive substring), summary line above
 * the list, empty-with-filter state + "Clear filters" CTA, `aria-pressed`
 * on chips, `aria-label` on the search input, `aria-live="polite"` on the
 * row container, card demoted to the bottom of the dashboard, test IDs per
 * design-spec §14.9.
 */

const BASE_STATUS = {
  schwab: { configured: true, valid: true, expires_at: '2026-08-01T00:00:00+00:00' },
  fred: { configured: true, valid: true },
  cache: { fresh: 12, stale: 0, very_stale: 0, total: 12 },
  journal: { positions_count: 1 },
};

const BASE_KPIS = {
  open_positions: 1,
  open_positions_breakdown: { stock: 0, csp: 0, cc: 0, wheel: 1, holding: 0 },
  notional_value: 17542,
  notional_change_pct: 0.021,
  open_legs: 1,
  open_legs_breakdown: { puts: 1, calls: 0 },
  unrealized_pl: 302,
  unrealized_pl_pct: 0.018,
};

const ACTIVITY = [
  {
    kind: 'trade_added',
    timestamp: '2026-05-10T09:42:00+00:00',
    ticker: 'AAPL',
    trade_type: 'sell_call',
    position_id: 'pos-aapl',
  },
  {
    kind: 'trade_added',
    timestamp: '2026-05-09T15:00:00+00:00',
    ticker: 'TSLA',
    trade_type: 'sell_put',
    position_id: 'pos-tsla',
  },
  {
    kind: 'session_saved',
    timestamp: '2026-05-08T13:00:00+00:00',
    session_name: 'AAPL vs DGS10 5y',
    session_id: 'sess-1',
  },
  {
    kind: 'session_saved',
    timestamp: '2026-05-07T11:00:00+00:00',
    session_name: 'NVDA momentum',
    session_id: 'sess-2',
  },
  {
    kind: 'import',
    timestamp: '2026-05-06T08:00:00+00:00',
    ticker: 'MSFT',
  },
];

const BASE_PAYLOAD = {
  generated_at: '2026-05-12T13:42:00+00:00',
  status: BASE_STATUS,
  kpis: BASE_KPIS,
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
  upcoming_expirations: [],
  recent_activity: ACTIVITY,
  data_meta: {
    is_stale: false,
    fetched_at: '2026-05-12T13:42:00+00:00',
    sources_unavailable: [],
  },
  next_actions: [],
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

test.describe('RecentActivityCard — V0.5.4 refactor (issue #153)', () => {
  test('renders summary, filter chips, search input, and rows', async ({ page }) => {
    await mockDashboard(page, BASE_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    await expect(page.getByTestId('dashboard-activity-card')).toBeVisible();

    // Summary line — "N events · last activity {date}" pattern.
    const summary = page.getByTestId('recent-activity-summary');
    await expect(summary).toBeVisible();
    await expect(summary).toContainText('5 events');
    await expect(summary).toContainText('last activity');

    // Filter chips — all four IDs render and have aria-pressed.
    for (const id of ['all', 'trades', 'sessions', 'imports']) {
      const chip = page.getByTestId(`recent-activity-filter-${id}`);
      await expect(chip).toBeVisible();
      await expect(chip).toHaveAttribute('aria-pressed', /true|false/);
    }

    // "All" is the default active chip.
    await expect(page.getByTestId('recent-activity-filter-all')).toHaveAttribute(
      'aria-pressed',
      'true'
    );

    // Search input — aria-label + test ID.
    const search = page.getByTestId('recent-activity-search');
    await expect(search).toBeVisible();
    await expect(search).toHaveAttribute('aria-label', 'Filter by ticker');

    // All 5 rows render in the default "All" view.
    await expect(page.getByTestId('dashboard-activity-row')).toHaveCount(5);
  });

  test('filter chips toggle exclusively — only one active at a time', async ({ page }) => {
    await mockDashboard(page, BASE_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    // Click "Trades" — only trade_added rows remain.
    await page.getByTestId('recent-activity-filter-trades').click();
    await expect(page.getByTestId('recent-activity-filter-trades')).toHaveAttribute(
      'aria-pressed',
      'true'
    );
    await expect(page.getByTestId('recent-activity-filter-all')).toHaveAttribute(
      'aria-pressed',
      'false'
    );
    await expect(page.getByTestId('recent-activity-filter-sessions')).toHaveAttribute(
      'aria-pressed',
      'false'
    );
    await expect(page.getByTestId('dashboard-activity-row')).toHaveCount(2);

    // Click "Sessions" — only session_saved rows remain; trades chip deactivates.
    await page.getByTestId('recent-activity-filter-sessions').click();
    await expect(page.getByTestId('recent-activity-filter-sessions')).toHaveAttribute(
      'aria-pressed',
      'true'
    );
    await expect(page.getByTestId('recent-activity-filter-trades')).toHaveAttribute(
      'aria-pressed',
      'false'
    );
    await expect(page.getByTestId('dashboard-activity-row')).toHaveCount(2);

    // Click "Imports" — only import-kind events remain (one row in fixture).
    await page.getByTestId('recent-activity-filter-imports').click();
    await expect(page.getByTestId('dashboard-activity-row')).toHaveCount(1);

    // Back to "All" — every row visible again.
    await page.getByTestId('recent-activity-filter-all').click();
    await expect(page.getByTestId('dashboard-activity-row')).toHaveCount(5);
  });

  test('ticker search filters rows (case-insensitive substring match)', async ({ page }) => {
    await mockDashboard(page, BASE_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const search = page.getByTestId('recent-activity-search');

    // Lower-case "aapl" matches AAPL.
    await search.fill('aapl');
    // Two AAPL events in the fixture (one trade + one session named "AAPL vs ...").
    // The session_saved event has no `ticker` field so only the trade matches.
    await expect(page.getByTestId('dashboard-activity-row')).toHaveCount(1);

    // Upper-case "TSLA" matches TSLA (case-insensitive).
    await search.fill('TSLA');
    await expect(page.getByTestId('dashboard-activity-row')).toHaveCount(1);

    // Substring "sl" matches both AAPL? no — only TSLA contains "sl".
    await search.fill('sl');
    await expect(page.getByTestId('dashboard-activity-row')).toHaveCount(1);

    // Clearing the input restores all rows.
    await search.fill('');
    await expect(page.getByTestId('dashboard-activity-row')).toHaveCount(5);
  });

  test('empty state when filter+search returns no results, with Clear filters CTA', async ({
    page,
  }) => {
    await mockDashboard(page, BASE_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    // Pick Sessions + a ticker the sessions don't carry — produces no matches.
    await page.getByTestId('recent-activity-filter-sessions').click();
    await page.getByTestId('recent-activity-search').fill('XYZQ');

    // No rows.
    await expect(page.getByTestId('dashboard-activity-row')).toHaveCount(0);

    // Empty-state message + clear-filters control.
    const card = page.getByTestId('dashboard-activity-card');
    await expect(card).toContainText('No matching activity');

    const clear = page.getByTestId('recent-activity-clear-filters');
    await expect(clear).toBeVisible();

    await clear.click();

    // Filters reset: "All" active, search empty, all rows back.
    await expect(page.getByTestId('recent-activity-filter-all')).toHaveAttribute(
      'aria-pressed',
      'true'
    );
    await expect(page.getByTestId('recent-activity-search')).toHaveValue('');
    await expect(page.getByTestId('dashboard-activity-row')).toHaveCount(5);
  });

  test('row container has aria-live="polite" so filter changes announce', async ({ page }) => {
    await mockDashboard(page, BASE_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    // The aria-live region wraps the rows / empty-state. Find it via the
    // descendant rows so the assertion is structural rather than coupled to a
    // class name.
    const liveRegion = page
      .getByTestId('dashboard-activity-card')
      .locator('[aria-live="polite"]');
    await expect(liveRegion).toHaveCount(1);
  });

  test('Recent Activity card is positioned last among dashboard sections', async ({ page }) => {
    await mockDashboard(page, BASE_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    // All standard sections must render before the activity card. Confirm
    // the activity card sits AFTER the positions card in DOM order, which
    // is the demoted-to-bottom guarantee from spec §2.7.
    const activityCard = page.getByTestId('dashboard-activity-card');
    const positionsCard = page.getByTestId('dashboard-positions-card');

    await expect(activityCard).toBeVisible();
    await expect(positionsCard).toBeVisible();

    const order = await activityCard.evaluate((activity, otherSelector) => {
      const other = document.querySelector(otherSelector);
      if (!other) return 'missing';
      // Node.DOCUMENT_POSITION_FOLLOWING (4) means `activity` follows `other`.
      return other.compareDocumentPosition(activity) & 4 ? 'after' : 'before';
    }, '[data-testid="dashboard-positions-card"]');

    expect(order).toBe('after');
  });

  test('pristine empty state (no events) hides filters and shows EmptyState copy', async ({
    page,
  }) => {
    await mockDashboard(page, { ...BASE_PAYLOAD, recent_activity: [] });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const card = page.getByTestId('dashboard-activity-card');
    await expect(card).toContainText('No activity yet');

    // Filter chips + search are not shown when there's nothing to filter —
    // we don't want to suggest filtering an empty list.
    await expect(page.getByTestId('recent-activity-filter-all')).toHaveCount(0);
    await expect(page.getByTestId('recent-activity-search')).toHaveCount(0);
    await expect(page.getByTestId('recent-activity-summary')).toHaveCount(0);
  });
});
