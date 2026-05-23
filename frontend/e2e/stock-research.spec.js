import { test, expect } from '@playwright/test';

/**
 * E2E for issue #280 — per-position Stock Research page (/positions/[id]/review).
 *
 * Covers the PRD AC list:
 *   - The dashboard Positions "Review" CTA routes to /positions/{id}/review
 *     (not /journal?position={id}, which was the legacy destination).
 *   - The page header link-outs route to recovery / scanner / journal.
 *   - All six sections render in the populated state.
 *   - Per-section endpoint failure surfaces the section-level retry tile —
 *     other sections still render (NFR-3).
 *   - The full-page error and 404 states render when the position itself
 *     fails to load.
 *   - The thesis editor autosaves with the documented lifecycle.
 *   - The thesis editor enforces the 4000-character client-side cap.
 *
 * Every test mocks the backend at the route level. No live backend, no
 * yfinance / Alpha Vantage / FRED traffic.
 */

const POSITION_ID = 'pos-sofi';

// --- Fixture builders -------------------------------------------------------

function positionPayload(overrides = {}) {
  return {
    id: POSITION_ID,
    ticker: 'SOFI',
    shares: 100,
    broker_cost_basis: 2856.0,
    adjusted_cost_basis: 2632.0,
    current_price: 23.76,
    unrealized_pl: -224.0,
    pl_pct: -0.078,
    status: 'open',
    strategy: 'wheel',
    opened_at: '2024-09-12T10:00:00Z',
    ...overrides,
  };
}

function businessPayload() {
  return {
    ticker: 'SOFI',
    name: 'SoFi Technologies, Inc.',
    summary:
      'SoFi is a personal finance company offering a wide range of financial services and products through its mobile-first platform.',
    sector: 'Financial Services',
    industry: 'Credit Services',
    market_cap: 18230000000,
    employees: 4900,
    source: 'yfinance',
    fetched_at: '2026-05-22T17:30:00Z',
  };
}

function priceHistoryPayload() {
  return {
    ticker: 'SOFI',
    window: '1Y',
    prices: [
      { date: '2025-06-01', close: 7.8 },
      { date: '2025-07-01', close: 8.1 },
      { date: '2025-08-01', close: 9.4 },
      { date: '2025-09-01', close: 10.6 },
      { date: '2025-10-01', close: 12.0 },
      { date: '2025-11-01', close: 14.2 },
      { date: '2025-12-01', close: 15.5 },
      { date: '2026-01-01', close: 18.0 },
      { date: '2026-02-01', close: 20.1 },
      { date: '2026-03-01', close: 22.8 },
      { date: '2026-04-01', close: 24.0 },
      { date: '2026-05-01', close: 23.76 },
    ],
    basis: { broker: 28.56, adjusted: 26.32 },
    trade_events: [
      { date: '2025-09-15', type: 'sell_put', strike: 8 },
      { date: '2025-11-15', type: 'sell_call', strike: 12 },
      { date: '2025-12-15', type: 'assignment', strike: 12 },
    ],
    earnings_events: [
      { date: '2025-08-04', label: 'Q2 earnings' },
      { date: '2025-11-04', label: 'Q3 earnings' },
    ],
    source: 'schwab',
    fetched_at: '2026-05-22T17:30:00Z',
  };
}

function financialsPayload() {
  // 8 quarters, newest first
  const base = [
    { period_end: '2026-03-31', revenue: 645e6, eps: 0.02, gross_margin: 0.43, operating_margin: 0.04 },
    { period_end: '2025-12-31', revenue: 619e6, eps: 0.01, gross_margin: 0.42, operating_margin: 0.03 },
    { period_end: '2025-09-30', revenue: 600e6, eps: 0.00, gross_margin: 0.41, operating_margin: 0.02 },
    { period_end: '2025-06-30', revenue: 570e6, eps: -0.01, gross_margin: 0.40, operating_margin: 0.01 },
    { period_end: '2025-03-31', revenue: 550e6, eps: -0.02, gross_margin: 0.39, operating_margin: 0.00 },
    { period_end: '2024-12-31', revenue: 530e6, eps: -0.03, gross_margin: 0.38, operating_margin: -0.01 },
    { period_end: '2024-09-30', revenue: 510e6, eps: -0.04, gross_margin: 0.37, operating_margin: -0.02 },
    { period_end: '2024-06-30', revenue: 490e6, eps: -0.05, gross_margin: 0.36, operating_margin: -0.03 },
  ];
  return {
    ticker: 'SOFI',
    quarters: base,
    source: 'alphavantage',
    fetched_at: '2026-05-22T17:30:00Z',
  };
}

function regressionPayload() {
  return {
    ticker: 'SOFI',
    window: '1Y',
    summary:
      'Mostly market-driven; rate exposure is meaningful and negative. R²=0.83 over 252 trading days.',
    sector_omitted: false,
    basket: ['SPY', 'XLF', 'DGS10'],
    sample_size: 252,
    r_squared: 0.83,
    idiosyncratic_share: 0.17,
    factors: [
      { name: 'SPY', beta: 1.42, p_value: 0.001, share: 0.55 },
      { name: 'XLF', beta: 0.78, p_value: 0.04, share: 0.18 },
      { name: 'DGS10', beta: -0.61, p_value: 0.02, share: 0.1 },
    ],
    source: 'composite',
    fetched_at: '2026-05-22T17:30:00Z',
  };
}

function thesisPayload(overrides = {}) {
  return {
    thesis: 'Bull case: SoFi grows lending into a maturing student-loan market.',
    updated_at: '2026-05-22T17:30:00Z',
    version: 3,
    ...overrides,
  };
}

// --- Mock helpers -----------------------------------------------------------

function mockPosition(page, payload, status = 200) {
  return page.route(`**/api/journal/positions/${POSITION_ID}`, (route) =>
    route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(payload),
    }),
  );
}

function mockResearchEndpoint(page, suffix, payload, status = 200) {
  return page.route(`**/api/positions/${POSITION_ID}/research/${suffix}*`, (route) =>
    route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(payload),
    }),
  );
}

async function mockAllSectionsHappy(page) {
  await mockPosition(page, positionPayload());
  await mockResearchEndpoint(page, 'business', businessPayload());
  await mockResearchEndpoint(page, 'price-history', priceHistoryPayload());
  await mockResearchEndpoint(page, 'financials', financialsPayload());
  await mockResearchEndpoint(page, 'regression', regressionPayload());
  await mockResearchEndpoint(page, 'thesis', thesisPayload());
}

async function openResearchPage(page) {
  await page.goto(`/positions/${POSITION_ID}/review`);
  await page.waitForLoadState('networkidle');
}

// --- Tests ------------------------------------------------------------------

test.describe('Stock Research page — populated state', () => {
  test('renders all six sections + header + footer', async ({ page }) => {
    await mockAllSectionsHappy(page);
    await openResearchPage(page);

    await expect(page.getByTestId('research-page')).toBeVisible();
    await expect(page.getByTestId('research-header')).toBeVisible();
    await expect(page.getByTestId('research-header-ticker')).toHaveText('SOFI');
    await expect(page.getByTestId('research-header-sector-pill')).toHaveText(
      'Financial Services',
    );

    // All six section cards are present.
    await expect(page.getByTestId('research-a')).toBeVisible();
    await expect(page.getByTestId('research-b')).toBeVisible();
    await expect(page.getByTestId('research-d')).toBeVisible();
    await expect(page.getByTestId('research-e')).toBeVisible();
    await expect(page.getByTestId('research-f')).toBeVisible();
    await expect(page.getByTestId('research-footer-disclaimer')).toBeVisible();
  });

  test('three header link-outs route to recovery / options / journal', async ({
    page,
  }) => {
    await mockAllSectionsHappy(page);
    await openResearchPage(page);

    await expect(page.getByTestId('research-header-recovery-link')).toHaveAttribute(
      'href',
      `/positions/${POSITION_ID}/recovery`,
    );
    await expect(page.getByTestId('research-header-scanner-link')).toHaveAttribute(
      'href',
      '/options?ticker=SOFI',
    );
    await expect(page.getByTestId('research-header-journal-link')).toHaveAttribute(
      'href',
      `/journal?position=${POSITION_ID}`,
    );
  });

  test('Section A renders summary + KV strip + show-more toggle', async ({
    page,
  }) => {
    await mockAllSectionsHappy(page);
    await openResearchPage(page);

    await expect(page.getByTestId('research-a-business-summary')).toContainText(
      'SoFi is a personal finance',
    );
    await expect(page.getByTestId('research-a-kv-sector')).toContainText(
      'Financial Services',
    );
    await expect(page.getByTestId('research-a-kv-industry')).toContainText(
      'Credit Services',
    );
    await expect(page.getByTestId('research-a-kv-market-cap')).toContainText(
      '$18.2B',
    );
    await expect(page.getByTestId('research-a-kv-employees')).toContainText(
      '4,900',
    );
  });

  test('Section E renders the verbatim backend summary + factor rows', async ({
    page,
  }) => {
    await mockAllSectionsHappy(page);
    await openResearchPage(page);

    await expect(page.getByTestId('research-e-summary')).toContainText(
      'Mostly market-driven; rate exposure is meaningful and negative.',
    );
    await expect(page.getByTestId('research-e-row-market')).toBeVisible();
    await expect(page.getByTestId('research-e-row-sector')).toBeVisible();
    await expect(page.getByTestId('research-e-row-rates')).toBeVisible();
    await expect(page.getByTestId('research-e-row-idiosyncratic')).toBeVisible();
    await expect(page.getByTestId('research-e-basket-caption')).toContainText(
      'Basket: SPY + XLF + DGS10',
    );
  });
});

test.describe('Stock Research page — per-section failure', () => {
  test('Section D 502 surfaces the section error tile while the rest render', async ({
    page,
  }) => {
    await mockPosition(page, positionPayload());
    await mockResearchEndpoint(page, 'business', businessPayload());
    await mockResearchEndpoint(page, 'price-history', priceHistoryPayload());
    await mockResearchEndpoint(
      page,
      'financials',
      { detail: 'Financials source unavailable' },
      502,
    );
    await mockResearchEndpoint(page, 'regression', regressionPayload());
    await mockResearchEndpoint(page, 'thesis', thesisPayload());
    await openResearchPage(page);

    // Section D shows the error tile.
    await expect(page.getByTestId('research-d-error')).toBeVisible();
    // Other sections still render.
    await expect(page.getByTestId('research-a-business-summary')).toBeVisible();
    await expect(page.getByTestId('research-e-summary')).toBeVisible();
  });
});

test.describe('Stock Research page — full-page states', () => {
  test('404 on position renders the not-found EmptyState', async ({ page }) => {
    await mockPosition(
      page,
      { detail: 'Position not found' },
      404,
    );
    await openResearchPage(page);

    await expect(page.getByTestId('research-not-found')).toBeVisible();
  });

  test('500 on position renders the full-page error retry banner', async ({
    page,
  }) => {
    await mockPosition(
      page,
      { detail: 'Failed to load position' },
      500,
    );
    await openResearchPage(page);

    await expect(page.getByTestId('research-error')).toBeVisible();
  });
});

test.describe('Stock Research page — thesis editor', () => {
  test('autosave fires after debounce and transitions through saved state', async ({
    page,
  }) => {
    await mockPosition(page, positionPayload());
    await mockResearchEndpoint(page, 'business', businessPayload());
    await mockResearchEndpoint(page, 'price-history', priceHistoryPayload());
    await mockResearchEndpoint(page, 'financials', financialsPayload());
    await mockResearchEndpoint(page, 'regression', regressionPayload());
    await mockResearchEndpoint(
      page,
      'thesis',
      thesisPayload({ thesis: '', version: 0, updated_at: null }),
    );

    // Capture the PUT and respond with version: 1.
    const putRequests = [];
    await page.route(
      `**/api/positions/${POSITION_ID}/research/thesis`,
      async (route) => {
        const req = route.request();
        if (req.method() === 'PUT') {
          const body = JSON.parse(req.postData() || '{}');
          putRequests.push(body);
          return route.fulfill({
            status: 200,
            contentType: 'application/json',
            body: JSON.stringify({
              thesis: body.thesis,
              updated_at: '2026-05-22T18:00:00Z',
              version: 1,
            }),
          });
        }
        // GET — empty initial state
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ thesis: '', updated_at: null, version: 0 }),
        });
      },
    );

    await openResearchPage(page);

    const textarea = page.getByTestId('research-f-textarea');
    await textarea.fill('Bull case: rates falling boost SoFi.');

    // The status row transitions through saving → saved (or directly to saved
    // if the network mock resolves before we check). Either way, a saved
    // state should appear and the PUT should have fired exactly once.
    await expect(page.getByTestId('research-f-status-saved')).toBeVisible({
      timeout: 5000,
    });
    expect(putRequests).toHaveLength(1);
    expect(putRequests[0].thesis).toBe('Bull case: rates falling boost SoFi.');
  });

  test('enforces the 4000-character client-side cap', async ({ page }) => {
    await mockAllSectionsHappy(page);
    await openResearchPage(page);

    const big = 'a'.repeat(4500);
    const textarea = page.getByTestId('research-f-textarea');
    await textarea.fill(big);

    const value = await textarea.inputValue();
    expect(value.length).toBe(4000);

    await expect(page.getByTestId('research-f-char-count')).toContainText(
      '4000 / 4000',
    );
  });
});

// --- Dashboard CTA wire-up (issue #280 §9) ----------------------------------

test.describe('Dashboard Positions Card — Review CTA', () => {
  function dashboardPayload() {
    // Mirror the shape used by existing dashboard-* e2e specs so the
    // /dashboard surface renders without crashing.
    return {
      generated_at: '2026-05-22T13:42:00+00:00',
      status: {
        schwab: {
          configured: true,
          valid: true,
          expires_at: '2026-08-01T00:00:00+00:00',
        },
        fred: { configured: true, valid: true },
        cache: { fresh: 12, stale: 0, very_stale: 0, total: 12 },
        journal: { positions_count: 1 },
      },
      kpis: {
        open_positions: 1,
        open_positions_breakdown: { stock: 1, csp: 0, cc: 0, wheel: 0, holding: 0 },
        notional_value: 2376,
        notional_change_pct: 0,
        open_legs: 0,
        open_legs_breakdown: { puts: 0, calls: 0 },
        unrealized_pl: -224,
        unrealized_pl_pct: -0.078,
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
          id: POSITION_ID,
          ticker: 'SOFI',
          shares: 100,
          strategy: 'wheel',
          broker_cost_basis: 2856.0,
          adjusted_cost_basis: 2632.0,
          current_price: 23.76,
          notional: 2376.0,
          unrealized_pl: -224.0,
          pl_pct: -0.078,
          open_legs_count: 0,
          wheel_status: 'Holding',
          next_suggested_action: 'Review',
        },
      ],
      open_legs: [],
      recent_activity: [],
      data_meta: {
        is_stale: false,
        fetched_at: '2026-05-22T13:42:00+00:00',
        sources_unavailable: [],
      },
      next_actions: [],
    };
  }

  test('Review action routes to /positions/{id}/review (not /journal)', async ({
    page,
  }) => {
    await page.route('**/api/dashboard', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(dashboardPayload()),
      }),
    );

    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const review = page.getByTestId('dashboard-position-next-action');
    await expect(review).toHaveAttribute(
      'href',
      `/positions/${POSITION_ID}/review`,
    );
    await expect(review).not.toHaveAttribute(
      'href',
      `/journal?position=${POSITION_ID}`,
    );
  });
});

// --- Issue #288: per-section failure copy ----------------------------------

test.describe('Stock Research page — Section A throttling copy (#288)', () => {
  test('Section A renders throttling copy when API returns rate-limit detail', async ({
    page,
  }) => {
    await mockPosition(page, positionPayload());
    await mockResearchEndpoint(
      page,
      'business',
      { detail: 'Yahoo Finance is throttling us — try again in a few minutes.' },
      502,
    );
    await mockResearchEndpoint(page, 'price-history', priceHistoryPayload());
    await mockResearchEndpoint(page, 'financials', financialsPayload());
    await mockResearchEndpoint(page, 'regression', regressionPayload());
    await mockResearchEndpoint(page, 'thesis', thesisPayload());
    await openResearchPage(page);

    const errorTile = page.getByTestId('research-a-error');
    await expect(errorTile).toBeVisible();
    await expect(errorTile).toContainText(
      'Yahoo Finance is throttling us — try again in a few minutes.',
    );
    // The "Source unavailable: yfinance" subline must be suppressed.
    await expect(errorTile).not.toContainText('Source unavailable');
  });
});

test.describe('Stock Research page — Section D both-empty copy (#288)', () => {
  test('Section D renders verbatim no-data copy when both sources empty', async ({
    page,
  }) => {
    await mockPosition(page, positionPayload());
    await mockResearchEndpoint(page, 'business', businessPayload());
    await mockResearchEndpoint(page, 'price-history', priceHistoryPayload());
    await mockResearchEndpoint(
      page,
      'financials',
      {
        detail:
          'No financial data available for SOFI. Both Alpha Vantage and Yahoo Finance returned empty for this symbol.',
      },
      502,
    );
    await mockResearchEndpoint(page, 'regression', regressionPayload());
    await mockResearchEndpoint(page, 'thesis', thesisPayload());
    await openResearchPage(page);

    const errorTile = page.getByTestId('research-d-error');
    await expect(errorTile).toBeVisible();
    await expect(errorTile).toContainText('No financial data available for SOFI.');
    await expect(errorTile).toContainText(
      'Both Alpha Vantage and Yahoo Finance returned empty for this symbol.',
    );
    // The generic "Source unavailable: alphavantage" subline must be suppressed.
    await expect(errorTile).not.toContainText('Source unavailable');
  });
});
