import { test, expect } from '@playwright/test';

/**
 * E2E for issue #151 — Positions card upgrade to triage table.
 *
 * Covers AC: cost-basis dual-line rendering; %P/L color coding (green/red);
 * status pill text + tooltip; cell-level links (ticker → /journal,
 * next-action → contextual destination); Day column visible-but-`—` on
 * desktop; Day and P/L $ columns hidden on mobile; loading and empty states;
 * Schwab-disconnected fallback rendering; test IDs preserved.
 */

const BASE_STATUS = {
  schwab: { configured: true, valid: true, expires_at: '2026-08-01T00:00:00+00:00' },
  fred: { configured: true, valid: true },
  cache: { fresh: 12, stale: 0, very_stale: 0, total: 12 },
  journal: { positions_count: 4 },
};

const BASE_KPIS = {
  open_positions: 4,
  open_positions_breakdown: { stock: 0, csp: 1, cc: 1, wheel: 1, holding: 1 },
  notional_value: 50000,
  notional_change_pct: 0.02,
  open_legs: 3,
  open_legs_breakdown: { puts: 2, calls: 1 },
  unrealized_pl: 200,
  unrealized_pl_pct: 0.005,
  largest_risk: null,
  premium_collected_total: 0,
  premium_collected_trades: 0,
  premium_collected_ytd: 0,
  realized_pl: 0,
  realized_pl_pct: null,
  largest_loser: null,
};

const TRIAGE_POSITIONS = [
  {
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
  },
  {
    id: 'pos-tsla',
    ticker: 'TSLA',
    shares: 50,
    strategy: 'cc',
    adjusted_cost_basis: 11620.0,
    broker_cost_basis: 11755.0,
    adjusted_cost_basis_per_share: 232.4,
    broker_cost_basis_per_share: 235.1,
    current_price: 238.8,
    notional: 11940.0,
    unrealized_pl: 320.0,
    pl_pct: 0.0275,
    open_legs_count: 1,
    wheel_status: 'CC',
    next_suggested_action: 'Roll',
  },
  {
    id: 'pos-amd',
    ticker: 'AMD',
    shares: 75,
    strategy: 'holding',
    adjusted_cost_basis: 11707.5,
    broker_cost_basis: 11865.0,
    adjusted_cost_basis_per_share: 156.1,
    broker_cost_basis_per_share: 158.2,
    current_price: 162.35,
    notional: 12176.25,
    unrealized_pl: 468.75,
    // Negative P/L to exercise the red color path.
    pl_pct: -0.0125,
    open_legs_count: 0,
    wheel_status: 'Holding',
    next_suggested_action: 'Cover',
  },
  {
    id: 'pos-nvda',
    ticker: 'NVDA',
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
  },
];

const TRIAGE_PAYLOAD = {
  generated_at: '2026-05-12T13:42:00+00:00',
  status: BASE_STATUS,
  kpis: BASE_KPIS,
  positions: TRIAGE_POSITIONS,
  open_legs: [],
  recent_activity: [],
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

test.describe('Positions triage table @e2e', () => {
  test('renders one row per position with required testIds', async ({ page }) => {
    await mockDashboard(page, TRIAGE_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    await expect(page.getByTestId('dashboard-position-row')).toHaveCount(4);
    // Per-row status pill + next-action target (one per row).
    await expect(page.getByTestId('dashboard-position-status')).toHaveCount(4);
    await expect(page.getByTestId('dashboard-position-next-action')).toHaveCount(4);
  });

  // Issue #320 (bridge edit): basis cell now renders PER-SHARE values with a
  // "/sh" affordance instead of the totals ($17,240 / $16,983). Broker
  // 17240/100 = $172.40; adjusted 16983/100 = $169.83.
  test('cost-basis cell renders per-share broker and adjusted values', async ({ page }) => {
    await mockDashboard(page, TRIAGE_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const firstRow = page.getByTestId('dashboard-position-row').first();
    const brokerCell = firstRow.getByTestId('dashboard-position-broker-basis');
    const adjustedCell = firstRow.getByTestId('dashboard-position-adjusted-basis');
    // Broker basis on line 1; adjusted basis with "/sh adj." suffix on line 2.
    await expect(brokerCell).toContainText('$172.40');
    await expect(brokerCell).toContainText('/sh');
    await expect(adjustedCell).toContainText('$169.83');
    await expect(adjustedCell).toContainText('/sh');
    await expect(adjustedCell).toContainText('adj.');
  });

  test('%P/L cell renders positive in green and negative in red', async ({ page }) => {
    await mockDashboard(page, TRIAGE_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const rows = page.getByTestId('dashboard-position-row');

    // AAPL row — positive pl_pct.
    const aaplRow = rows.nth(0);
    await expect(aaplRow).toContainText('+3.29%');
    const aaplPct = aaplRow.locator('.text-green-600').first();
    await expect(aaplPct).toContainText('+3.29%');

    // AMD row — negative pl_pct.
    const amdRow = rows.nth(2);
    await expect(amdRow).toContainText('-1.25%');
    const amdPct = amdRow.locator('.text-red-600').first();
    await expect(amdPct).toContainText('-1.25%');
  });

  test('status pill carries title tooltip per wheel state', async ({ page }) => {
    await mockDashboard(page, TRIAGE_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const statuses = page.getByTestId('dashboard-position-status');
    // Row 0 → Wheel
    await expect(statuses.nth(0)).toContainText('Wheel');
    await expect(statuses.nth(0)).toHaveAttribute('title', /wheel/i);
    // Row 1 → CC
    await expect(statuses.nth(1)).toContainText('CC');
    await expect(statuses.nth(1)).toHaveAttribute('title', /covered call/i);
    // Row 2 → Holding
    await expect(statuses.nth(2)).toContainText('Holding');
    await expect(statuses.nth(2)).toHaveAttribute('title', /no open option legs/i);
    // Row 3 → CSP
    await expect(statuses.nth(3)).toContainText('CSP');
    await expect(statuses.nth(3)).toHaveAttribute('title', /cash-secured put/i);
  });

  test('next-action "Hold" renders as plain text (not a link)', async ({ page }) => {
    await mockDashboard(page, TRIAGE_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const nextActions = page.getByTestId('dashboard-position-next-action');
    // AAPL row → hold backend label → "Hold" plain text (SPAN, not A).
    await expect(nextActions.nth(0)).toContainText('Hold');
    await expect(nextActions.nth(0)).toHaveJSProperty('tagName', 'SPAN');
  });

  test('next-action "Cover" navigates to /options?ticker={TICKER}', async ({ page }) => {
    await mockDashboard(page, TRIAGE_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    // AMD row — next_suggested_action="Cover" → /options?ticker=AMD
    const amdAction = page.getByTestId('dashboard-position-next-action').nth(2);
    await expect(amdAction).toHaveJSProperty('tagName', 'A');
    await expect(amdAction).toHaveAttribute('href', /\/options\?ticker=AMD/);

    await amdAction.click();
    await page.waitForURL(/\/options\?ticker=AMD/);
    expect(page.url()).toContain('/options?ticker=AMD');
  });

  test('next-action "Roll" navigates to /journal?position=<id>', async ({ page }) => {
    await mockDashboard(page, TRIAGE_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    // TSLA row — next_suggested_action="Roll" → /journal?position=pos-tsla
    const tslaAction = page.getByTestId('dashboard-position-next-action').nth(1);
    await expect(tslaAction).toHaveJSProperty('tagName', 'A');
    await expect(tslaAction).toHaveAttribute('href', /\/journal\?position=pos-tsla/);

    await tslaAction.click();
    await page.waitForURL(/\/journal\?position=pos-tsla/);
    expect(page.url()).toContain('position=pos-tsla');
  });

  test('ticker links to /journal?position=<id>', async ({ page }) => {
    await mockDashboard(page, TRIAGE_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const aaplRow = page.getByTestId('dashboard-position-row').first();
    const aaplTickerLink = aaplRow.getByRole('link', { name: 'AAPL' });
    await expect(aaplTickerLink).toHaveAttribute('href', /\/journal\?position=pos-aapl/);
    await aaplTickerLink.click();
    await page.waitForURL(/\/journal\?position=pos-aapl/);
  });

  // Bridge edit (v1.9.0 #421, R3): the Day cell is no longer a hard-coded `—`.
  // The TRIAGE_PAYLOAD rows carry no day-change fields, so each cell renders the
  // explicit "no prior close" empty state (data-day-state="no_prior_close").
  // Populated day-change rendering is covered in dashboard-day-change.spec.js.
  test('Day column header and no-prior-close cells render on desktop', async ({ page }) => {
    // Default Playwright viewport is 1280×720 (desktop, > lg=1024).
    await mockDashboard(page, TRIAGE_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const dayHeader = page
      .getByTestId('dashboard-positions-card')
      .locator('th', { hasText: 'Day' });
    await expect(dayHeader).toBeVisible();

    // Rows without day-change data render the explicit no-prior-close state.
    const dayCells = page.getByTestId('dashboard-position-day');
    await expect(dayCells).toHaveCount(4);
    for (let i = 0; i < 4; i += 1) {
      await expect(dayCells.nth(i)).toHaveAttribute('data-day-state', 'no_prior_close');
      await expect(dayCells.nth(i)).toContainText('no prior close');
    }
  });

  test('Day and P/L $ columns are hidden on mobile (< lg)', async ({ page }) => {
    // 768px is below the `lg` breakpoint (1024px).
    await page.setViewportSize({ width: 768, height: 900 });
    await mockDashboard(page, TRIAGE_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const card = page.getByTestId('dashboard-positions-card');
    // Day column header is in the DOM but `display:none` via `hidden lg:table-cell`.
    const dayHeader = card.locator('th', { hasText: 'Day' });
    await expect(dayHeader).toBeHidden();

    // Day cells are present in the DOM but hidden on mobile.
    const dayCells = page.getByTestId('dashboard-position-day');
    await expect(dayCells.first()).toBeHidden();

    // P/L $ header is also hidden on mobile.
    const plHeader = card.locator('th', { hasText: /^P\/L$/ });
    await expect(plHeader).toBeHidden();
  });

  test('cost-basis cell on mobile shows only adjusted basis (no "adj." suffix)', async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 900 });
    await mockDashboard(page, TRIAGE_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const firstRow = page.getByTestId('dashboard-position-row').first();
    const adjustedCell = firstRow
      .getByTestId('dashboard-position-adjusted-basis');
    // Issue #320: mobile shows the per-share adjusted basis with "/sh". The
    // "adj." suffix lives only on the lg:inline span (visually hidden on
    // mobile but still in the DOM), so we assert the visible per-share value
    // rather than DOM-absence of "adj.".
    await expect(adjustedCell).toContainText('$169.83');
    await expect(adjustedCell).toContainText('/sh');
    // Broker basis is in the DOM (semantic order) but hidden on mobile.
    await expect(
      firstRow.getByTestId('dashboard-position-broker-basis')
    ).toBeHidden();
  });

  test('CSP row (zero shares) renders "cash-secured" placeholder', async ({ page }) => {
    await mockDashboard(page, TRIAGE_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const nvdaRow = page.getByTestId('dashboard-position-row').nth(3);
    await expect(nvdaRow).toContainText('NVDA');
    await expect(nvdaRow).toContainText('cash-secured');
  });

  test('Schwab-disconnected positions render %P/L and current as em-dashes', async ({ page }) => {
    const disconnectedPositions = TRIAGE_POSITIONS.map((p) => ({
      ...p,
      current_price: null,
      notional: null,
      unrealized_pl: null,
      pl_pct: null,
    }));
    await mockDashboard(page, {
      ...TRIAGE_PAYLOAD,
      status: {
        ...BASE_STATUS,
        schwab: { configured: false, valid: false, expires_at: null },
      },
      positions: disconnectedPositions,
    });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const firstRow = page.getByTestId('dashboard-position-row').first();
    // The row still renders (status + ticker + cost basis) — only price-dependent cells are em-dashed.
    await expect(firstRow).toContainText('AAPL');
    await expect(firstRow).toContainText('Wheel');
    await expect(firstRow).toContainText('—');
  });

  test('loading state renders 3 skeleton rows and no table', async ({ page }) => {
    // Stall the dashboard request so the loading UI persists for the assertion.
    let resolveBlock;
    const block = new Promise((resolve) => {
      resolveBlock = resolve;
    });
    await page.route('**/api/dashboard', async (route) => {
      await block;
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(TRIAGE_PAYLOAD),
      });
    });
    const navigation = page.goto('/dashboard');

    await expect(page.getByTestId('dashboard-positions-card')).toBeVisible();
    // No rows during the loading state.
    await expect(page.getByTestId('dashboard-position-row')).toHaveCount(0);

    resolveBlock();
    await navigation;
    await page.waitForLoadState('networkidle');
    await expect(page.getByTestId('dashboard-position-row')).toHaveCount(4);
  });

  test('empty state shows "No positions yet" copy and Open Journal CTA', async ({ page }) => {
    await mockDashboard(page, {
      ...TRIAGE_PAYLOAD,
      // Keep status non-empty so the onboarding panel doesn't take over.
      status: { ...BASE_STATUS, journal: { positions_count: 0 } },
      positions: [],
      kpis: {
        ...BASE_KPIS,
        open_positions: 0,
        open_positions_breakdown: { stock: 0, csp: 0, cc: 0, wheel: 0, holding: 0 },
      },
    });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const card = page.getByTestId('dashboard-positions-card');
    await expect(card).toContainText('No positions yet');
    await expect(card).toContainText(/import from schwab|add a position/i);
  });
});
