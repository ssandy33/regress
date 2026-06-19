import { test, expect } from '@playwright/test';

/**
 * E2E for issue #362 — "See full analysis →" bridge link.
 *
 * Decision: Option 3 (design spec issue-362-review-gap.md §1) — the inline
 * `Open option legs` inspect panel gets ONE tertiary text link that navigates
 * to the dedicated BTC-detail screen for the same leg. No new backend data;
 * the route is built from `leg.position_id` + `leg.id`, already on the leg.
 *
 * Covers AC1 (the inline panel clearly links to the deep view) + AC2
 * (Playwright coverage). Frontend has no unit/integration tier; coverage is
 * E2E-only per the spec's Test List (§10).
 *
 * Both the dashboard endpoint (source) and the BTC endpoint (destination) are
 * route-mocked — no live backend or Schwab quote required.
 */

const POSITION_ID = 'pos-aapl';

const BASE_PAYLOAD = {
  generated_at: '2026-06-18T13:42:00+00:00',
  status: {
    schwab: { configured: true, valid: true, expires_at: '2026-08-01T00:00:00+00:00' },
    fred: { configured: true, valid: true },
    cache: { fresh: 12, stale: 0, very_stale: 0, total: 12 },
    journal: { positions_count: 1 },
  },
  kpis: {
    open_positions: 1,
    open_positions_breakdown: { stock: 0, csp: 0, cc: 1, wheel: 0, holding: 0 },
    notional_value: 17542,
    notional_change_pct: 0,
    open_legs: 1,
    open_legs_breakdown: { puts: 0, calls: 1 },
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
  positions: [],
  recent_activity: [],
  data_meta: {
    is_stale: false,
    fetched_at: '2026-06-18T13:42:00+00:00',
    sources_unavailable: [],
  },
  next_actions: [],
};

const VERDICT_LABEL = {
  hold: 'Hold',
  profit_take_review: 'Review · 50%',
  dte_review: 'Review · 21d',
  expiration: 'Close · exp',
  assignment: 'Close · ITM',
};

function makeTriggeredRules(verdict) {
  const ids = ['assignment_risk', 'expiration_warning', 'profit_review', 'dte_review'];
  const governingId = {
    assignment: 'assignment_risk',
    expiration: 'expiration_warning',
    profit_take_review: 'profit_review',
    dte_review: 'dte_review',
  }[verdict];
  return ids.map((rule_id) => ({
    rule_id,
    metric_label: rule_id === 'profit_review' ? 'Premium captured' : 'Days to expiration',
    value_display: '—',
    rule_display: 'Review at ≥ 50%',
    status: rule_id === governingId ? 'triggered' : 'no',
    is_governing: rule_id === governingId,
    reasoning: rule_id === governingId ? 'Your rule triggered.' : null,
  }));
}

function makeLeg(overrides = {}) {
  const verdict = overrides.verdict || 'hold';
  return {
    id: 'leg-f15c',
    ticker: 'F',
    type: 'call',
    strike: 15.0,
    expiration: '2026-06-26',
    dte: 38,
    moneyness: { state: 'OTM', distance_pct: 0.124, distance_dollars: 1.86 },
    position_id: POSITION_ID,
    profit_target_status: { captured_pct: 0.5957, state: 'captured_50' },
    assignment_risk: 'low',
    suggested_action: 'hold',
    earnings_in_window: false,
    verdict,
    verdict_label: VERDICT_LABEL[verdict],
    reasoning:
      verdict === 'hold'
        ? 'No management rule has triggered for this leg yet.'
        : 'Your rule triggered.',
    triggered_rules: makeTriggeredRules(verdict),
    coverage: 'covered',
    premium: 0.3834,
    pnl_dollars: 22.84,
    cost_to_close: 15.5,
    ...overrides,
  };
}

function mockDashboard(page, legs) {
  return page.route('**/api/dashboard', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...BASE_PAYLOAD, open_legs: legs }),
    })
  );
}

// Minimal BTC-detail payload so the destination renders `btc-detail-page`.
function mockBtcDetail(page, legId, ticker = 'F', strike = 15.0) {
  return page.route(
    `**/api/positions/${POSITION_ID}/legs/${legId}/btc`,
    (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          state: 'populated',
          leg: {
            id: legId,
            position_id: POSITION_ID,
            ticker,
            strike,
            option_type: 'C',
            contracts: 1,
            expiration: '2026-06-26',
            dte: 38,
            moneyness: 'OTM',
            position_label: `${ticker} covered call`,
          },
          verdict: 'profit_take_review',
          economics: {
            credit_received: 38.34,
            current_option_mid: 15.72,
            cost_to_close: 15.72,
            captured_pct: 0.59,
            est_pl_if_closed: 22.62,
            pricing_as_of: '2026-06-18T14:32:00+00:00',
            pricing_source: 'live',
          },
          analysis: null,
          triggered_rules: [],
          disclaimer: 'This buy-to-close review reports your own Management Triggers.',
        }),
      })
  );
}

async function expandFirstLeg(page) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/dashboard');
  await page.waitForLoadState('networkidle');
  await page.getByTestId('dashboard-leg-row').first().click();
}

test.describe('Leg "See full analysis" bridge link (#362) @e2e', () => {
  // E1 — the load-bearing visibility assertion (critical path).
  test('inline Review panel shows "See full analysis" link when a leg row is expanded @smoke @e2e', async ({
    page,
  }) => {
    await mockDashboard(page, [makeLeg({ verdict: 'profit_take_review' })]);
    await expandFirstLeg(page);

    const cta = page.getByTestId('dashboard-leg-inspect-cta-full-leg-f15c');
    await expect(cta).toBeVisible();
    await expect(cta).toContainText('See full analysis');
  });

  // E2 — the bridge reaches the deep view (AC1).
  test('"See full analysis" link navigates to the BTC-detail screen for the same leg @e2e', async ({
    page,
  }) => {
    await mockDashboard(page, [makeLeg({ verdict: 'profit_take_review' })]);
    await mockBtcDetail(page, 'leg-f15c');
    await expandFirstLeg(page);

    const cta = page.getByTestId('dashboard-leg-inspect-cta-full-leg-f15c');
    await expect(cta).toHaveAttribute(
      'href',
      `/positions/${POSITION_ID}/legs/leg-f15c/btc`
    );
    await cta.click();
    await expect(page).toHaveURL(
      new RegExp(`/positions/${POSITION_ID}/legs/leg-f15c/btc$`)
    );
    await expect(page.getByTestId('btc-detail-page')).toBeVisible();
    await expect(page.getByTestId('btc-detail-leg-header')).toContainText('F');
  });

  // E3 — present on a quiet (no-rule) leg, even when "Log buy-to-close" is absent.
  test('"See full analysis" link is present on a quiet (no-rule) leg @e2e', async ({ page }) => {
    await mockDashboard(page, [makeLeg({ id: 'leg-quiet', verdict: 'hold' })]);
    await expandFirstLeg(page);

    await expect(page.getByTestId('dashboard-leg-inspect-cta-full-leg-quiet')).toBeVisible();
    // The "Log buy-to-close" CTA is gated on a closing verdict — absent here.
    await expect(page.getByTestId('dashboard-leg-inspect-cta-close-leg-quiet')).toHaveCount(0);
  });

  // E4 — on a closing verdict there is NO close-action button (#364: regress
  // journals, it doesn't execute); the bridge link still leads the CTA row.
  test('"See full analysis" leads the CTA row; no close-action button on a closing-verdict leg @e2e', async ({
    page,
  }) => {
    await mockDashboard(page, [makeLeg({ id: 'leg-close', verdict: 'profit_take_review' })]);
    await expandFirstLeg(page);

    const full = page.getByTestId('dashboard-leg-inspect-cta-full-leg-close');
    const journal = page.getByTestId('dashboard-leg-inspect-cta-journal-leg-close');
    await expect(full).toBeVisible();
    await expect(journal).toBeVisible();
    // #364 — no trade-action button, even on a closing verdict.
    await expect(page.getByTestId('dashboard-leg-inspect-cta-close-leg-close')).toHaveCount(0);

    // "See full analysis" leads the row: its DOM position precedes "Open in Journal".
    const fullThenJournal = await full.evaluate(
      (el, other) =>
        !!(el.compareDocumentPosition(other) & Node.DOCUMENT_POSITION_FOLLOWING),
      await journal.elementHandle()
    );
    expect(fullThenJournal).toBe(true);
  });
});
