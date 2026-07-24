import { test, expect } from '@playwright/test';

/**
 * E2E for issue #420 — dashboard account totals reconcile to the brokerage.
 *
 * Covers AC:
 *   - Account Summary strip renders account value + cash + day change (R1/R2/R3).
 *   - Account value reconciles to the broker net-liq (`data-reconciles`).
 *   - "Notional value" tile is renamed "Portfolio value" and, with the
 *     Unrealized P/L tile, carries the "incl. options" affordance +
 *     `data-includes-options` when option legs roll into the totals (R4).
 *   - Broker-not-connected → explicit "Connect Schwab to reconcile" empty
 *     state, not a false $0.
 */

const BASE_PAYLOAD = {
  generated_at: '2026-07-04T13:42:00+00:00',
  status: {
    schwab: { configured: true, valid: true, expires_at: '2026-09-01T00:00:00+00:00' },
    fred: { configured: true, valid: true },
    cache: { fresh: 12, stale: 0, very_stale: 0, total: 12 },
    journal: { positions_count: 1 },
  },
  positions: [
    {
      id: 'pos-sofi',
      ticker: 'SOFI',
      shares: 100,
      strategy: 'wheel',
      adjusted_cost_basis: 9166.0,
      current_price: 91.66,
      notional: 9166.0,
      unrealized_pl: 0.0,
      open_legs_count: 1,
    },
  ],
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
};

const KPIS = {
  open_positions: 1,
  open_positions_breakdown: { stock: 0, csp: 0, cc: 0, wheel: 1, holding: 0 },
  notional_value: 9161.5,
  notional_change_pct: 0.0,
  open_legs: 1,
  open_legs_breakdown: { puts: 0, calls: 1 },
  unrealized_pl: -4.5,
  unrealized_pl_pct: -0.0005,
  includes_options: true,
  largest_risk: null,
  premium_collected_total: 0,
  premium_collected_trades: 0,
  premium_collected_ytd: 0,
  realized_pl: 0,
  realized_pl_pct: null,
  largest_loser: null,
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

test.describe('Dashboard account parity (#420) @e2e', () => {
  test('Account Summary strip reconciles + renders value/cash tiles', async ({ page }) => {
    await mockDashboard(page, { ...BASE_PAYLOAD, kpis: KPIS });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const strip = page.getByTestId('dashboard-account-summary');
    await expect(strip).toBeVisible();

    const accountValue = page.getByTestId('kpi-account-value');
    await expect(accountValue).toContainText('$10,526.76');
    await expect(accountValue).toHaveAttribute('data-reconciles', 'true');
    await expect(accountValue).toHaveAttribute('data-reconcile-state', 'reconciled');
    // Reconciliation breakdown is traceable in the subtext.
    await expect(accountValue).toContainText('Equity $9,166.00');
    await expect(accountValue).toContainText('Cash $1,365.26');
    // Quiet reconciled badge (sibling of the tile within the hero wrapper).
    await expect(page.locator('[data-reconcile-badge="reconciled"]')).toContainText(
      'reconciled with broker'
    );

    await expect(page.getByTestId('kpi-cash')).toContainText('$1,365.26');
  });

  test('Portfolio value + Unrealized P/L tiles carry the incl.-options affordance (R4)', async ({ page }) => {
    await mockDashboard(page, { ...BASE_PAYLOAD, kpis: KPIS });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const portfolio = page.getByTestId('kpi-notional');
    // Renamed label (PRD decision #2) — testid stays kpi-notional.
    await expect(portfolio).toContainText('Portfolio value');
    await expect(portfolio).not.toContainText('Notional value');
    await expect(portfolio).toHaveAttribute('data-includes-options', 'true');
    await expect(portfolio).toContainText('incl. options');

    const unrealized = page.getByTestId('kpi-unrealized-pl');
    await expect(unrealized).toHaveAttribute('data-includes-options', 'true');
  });

  test('broker not connected → "Connect Schwab to reconcile" empty state, not $0', async ({ page }) => {
    const disconnected = {
      ...BASE_PAYLOAD,
      status: {
        ...BASE_PAYLOAD.status,
        schwab: { configured: false, valid: false, expires_at: null },
      },
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
    };
    await mockDashboard(page, { ...disconnected, kpis: KPIS });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const accountValue = page.getByTestId('kpi-account-value');
    await expect(accountValue).toContainText('Connect Schwab to reconcile');
    await expect(accountValue).toHaveAttribute('data-reconciles', 'false');
    // Cash renders an em-dash, never a false $0.
    await expect(page.getByTestId('kpi-cash')).toContainText('—');
    await expect(page.getByTestId('kpi-cash')).not.toContainText('$0');
  });

  test('reconcile_state=unavailable → muted "reconcile unavailable", not alarming (#429)', async ({
    page,
  }) => {
    const stale = {
      ...BASE_PAYLOAD,
      account_summary: {
        ...BASE_PAYLOAD.account_summary,
        reconciles: false,
        reconcile_state: 'unavailable',
      },
    };
    await mockDashboard(page, { ...stale, kpis: KPIS });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const accountValue = page.getByTestId('kpi-account-value');
    // Headline value still renders (ties to the positions below).
    await expect(accountValue).toContainText('$10,526.76');
    await expect(accountValue).toHaveAttribute('data-reconcile-state', 'unavailable');
    await expect(accountValue).toHaveAttribute('data-reconciles', 'false');
    // Muted "can't confirm" copy — NOT a red "doesn't match".
    await expect(page.locator('[data-reconcile-badge="unavailable"]')).toContainText(
      'reconcile unavailable'
    );
    await expect(page.locator('[data-reconcile-badge="mismatch"]')).toHaveCount(0);
  });

  test('reconcile_state=mismatch → alarming "doesn\'t match broker" (#429)', async ({
    page,
  }) => {
    const mismatch = {
      ...BASE_PAYLOAD,
      account_summary: {
        ...BASE_PAYLOAD.account_summary,
        reconciles: false,
        reconcile_state: 'mismatch',
      },
    };
    await mockDashboard(page, { ...mismatch, kpis: KPIS });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const accountValue = page.getByTestId('kpi-account-value');
    await expect(accountValue).toHaveAttribute('data-reconcile-state', 'mismatch');
    await expect(accountValue).toHaveAttribute('data-reconciles', 'false');
    await expect(page.locator('[data-reconcile-badge="mismatch"]')).toContainText(
      "doesn't match broker"
    );
  });

  test('reconcile badge renders INSIDE the account tile; strip tiles share height parity (#436)', async ({
    page,
  }) => {
    await mockDashboard(page, { ...BASE_PAYLOAD, kpis: KPIS });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    // The badge is a DESCENDANT of the account-value tile's bordered box —
    // not a sibling floating below it (the #436 defect).
    const accountValue = page.getByTestId('kpi-account-value');
    await expect(
      accountValue.locator('[data-reconcile-badge="reconciled"]')
    ).toHaveCount(1);

    // The three tiles in the reconciliation strip share one height baseline
    // (the badge no longer makes the account tile taller than its neighbours).
    const [aBox, cBox, dBox] = await Promise.all([
      page.getByTestId('kpi-account-value').boundingBox(),
      page.getByTestId('kpi-cash').boundingBox(),
      page.getByTestId('kpi-day-change').boundingBox(),
    ]);
    expect(aBox).not.toBeNull();
    expect(cBox).not.toBeNull();
    expect(dBox).not.toBeNull();
    // Allow 1px for sub-pixel rounding.
    expect(Math.abs(aBox.height - cBox.height)).toBeLessThanOrEqual(1);
    expect(Math.abs(aBox.height - dBox.height)).toBeLessThanOrEqual(1);
  });
});
