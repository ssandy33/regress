import { test, expect } from '@playwright/test';

/**
 * E2E for issue #244 — dedicated buy-to-close (BTC) leg detail screen.
 *
 * Covers the issue's AC:
 *   - The new route /positions/[id]/legs/[legId]/btc renders for a valid leg
 *     and shows the rule audit + BTC economics + recommended action.
 *   - A 404 renders the leg-not-found EmptyState (distinct from a network
 *     error state).
 *   - The screen is reachable via the "Review buy-to-close →" card CTA from both the
 *     profit-take and the DTE-review action cards on the dashboard.
 *   - States: loading skeleton, error + retry, no-rule-triggered, and the
 *     pricing-unavailable degraded variant.
 *   - Journal pre-fill: clicking "Buy to close" lands on the journal with
 *     ?action=close-leg and pre-fills the inverse-close trade form. Degrades
 *     gracefully when the leg param does not resolve.
 *
 * Every test mocks the BTC endpoint (and, for the CTA tests, the dashboard
 * endpoint) at the route level — no live backend or Schwab quote required.
 */

const POSITION_ID = 'pos-ford';
const LEG_ID = 'leg-ford-15c';
const BTC_ROUTE = `/positions/${POSITION_ID}/legs/${LEG_ID}/btc`;

const DISCLAIMER =
  'This buy-to-close review reports what your own Management Triggers said about this leg.';

// --- Fixture builders -------------------------------------------------------

function triggeredRules(verdict) {
  const govern = (id) => verdict === id;
  return [
    {
      rule_id: 'assignment_risk',
      metric_label: 'Assignment risk',
      value_display: verdict === 'assignment' ? 'High' : 'Low',
      rule_display: 'Review at ≥ High',
      status: verdict === 'assignment' ? 'triggered' : 'no',
      is_governing: govern('assignment'),
      reasoning: govern('assignment')
        ? 'Your expiration rule triggered and this leg is ITM.'
        : null,
    },
    {
      rule_id: 'expiration_warning',
      metric_label: 'Days to expiration',
      value_display: '38 d',
      rule_display: 'Warn at ≤ 7 d',
      status: verdict === 'expiration' ? 'triggered' : 'not_yet',
      is_governing: govern('expiration'),
      reasoning: govern('expiration')
        ? 'Your expiration rule triggered — 4 days to expiration.'
        : null,
    },
    {
      rule_id: 'profit_review',
      metric_label: 'Premium captured',
      value_display: '59%',
      rule_display: 'Review at ≥ 50%',
      status: verdict === 'profit_take_review' ? 'triggered' : 'not_yet',
      is_governing: govern('profit_take_review'),
      reasoning: govern('profit_take_review')
        ? 'Your 50% profit-take rule triggered. This leg has captured 59% of its max premium — past the 50% review threshold you set.'
        : null,
    },
    {
      rule_id: 'dte_review',
      metric_label: 'Days to expiration',
      value_display: '38 d',
      rule_display: 'Review at ≤ 21 d',
      status: verdict === 'dte_review' ? 'triggered' : 'not_yet',
      is_governing: govern('dte_review'),
      reasoning: govern('dte_review')
        ? 'This leg is inside your 21-day review window. Your rule says: decide — hold, roll, or close.'
        : null,
    },
  ];
}

function populatedPayload(overrides = {}) {
  const verdict = overrides.verdict || 'profit_take_review';
  return {
    state: 'populated',
    leg: {
      id: LEG_ID,
      position_id: POSITION_ID,
      ticker: 'F',
      strike: 15.0,
      option_type: 'C',
      contracts: 1,
      expiration: '2026-06-26',
      dte: 38,
      moneyness: 'OTM',
      position_label: 'F covered call',
      ...overrides.leg,
    },
    verdict,
    economics: {
      credit_received: 38.34,
      current_option_mid: 15.72,
      cost_to_close: 15.72,
      captured_pct: 0.59,
      est_pl_if_closed: 22.62,
      pricing_as_of: '2026-05-19T14:32:00+00:00',
      pricing_source: 'live',
      ...overrides.economics,
    },
    analysis:
      overrides.analysis !== undefined ? overrides.analysis : analysisBlock(),
    triggered_rules: overrides.triggered_rules || triggeredRules(verdict),
    disclaimer: DISCLAIMER,
  };
}

// Canonical F 14.5C analysis block (issue #319): S=16.29, K=14.5, O=1.93 →
// intrinsic 1.79, extrinsic 0.14, ext% 7%, breakeven 16.43, delta −0.14.
function analysisBlock(overrides = {}) {
  return {
    available: true,
    intrinsic: 1.79,
    extrinsic: 0.14,
    extrinsic_pct_of_mid: 0.0725,
    option_mid: 1.93,
    btc_breakeven: 16.43,
    underlying: 16.29,
    breakeven_delta: -0.14,
    scenarios: [
      { underlying: 14.66, label: '−10%', let_assign: 1450.0, btc_and_hold: 1273.0, delta: -177.0, winner: 'assign' },
      { underlying: 16.29, label: 'Flat', let_assign: 1450.0, btc_and_hold: 1436.0, delta: -14.0, winner: 'assign' },
      { underlying: 17.1, label: '+5%', let_assign: 1450.0, btc_and_hold: 1517.0, delta: 67.0, winner: 'btc' },
      { underlying: 17.92, label: '+10%', let_assign: 1450.0, btc_and_hold: 1599.0, delta: 149.0, winner: 'btc' },
    ],
    ...overrides,
  };
}

function degradedAnalysisBlock() {
  return {
    available: false,
    intrinsic: null,
    extrinsic: null,
    extrinsic_pct_of_mid: null,
    option_mid: null,
    btc_breakeven: null,
    underlying: null,
    breakeven_delta: null,
    scenarios: [],
  };
}

function noRulePayload() {
  const payload = populatedPayload({ verdict: 'hold' });
  payload.state = 'no-rule-triggered';
  return payload;
}

function pricingUnavailablePayload() {
  return populatedPayload({
    verdict: 'dte_review',
    economics: {
      credit_received: 61.0,
      current_option_mid: null,
      cost_to_close: null,
      captured_pct: null,
      est_pl_if_closed: null,
      pricing_as_of: null,
      pricing_source: 'unavailable',
    },
    analysis: degradedAnalysisBlock(),
  });
}

// --- Route mocks ------------------------------------------------------------

function mockBtcDetail(page, payload, status = 200, legId = LEG_ID) {
  return page.route(
    `**/api/positions/${POSITION_ID}/legs/${legId}/btc`,
    (route) =>
      route.fulfill({
        status,
        contentType: 'application/json',
        body: JSON.stringify(payload),
      }),
  );
}

async function openBtcDetail(page, route = BTC_ROUTE) {
  await page.goto(route);
  await page.waitForLoadState('networkidle');
}

// --- Dashboard fixtures for the CTA-navigation tests ------------------------

const DASHBOARD_BASE = {
  generated_at: '2026-05-19T13:42:00+00:00',
  status: {
    schwab: { configured: true, valid: true, expires_at: '2026-08-01T00:00:00+00:00' },
    fred: { configured: true, valid: true },
    cache: { fresh: 12, stale: 0, very_stale: 0, total: 12 },
    journal: { positions_count: 1 },
  },
  kpis: {
    open_positions: 1,
    open_positions_breakdown: { stock: 0, csp: 0, cc: 0, wheel: 1, holding: 0 },
    notional_value: 1550,
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
  open_legs: [],
  recent_activity: [],
  data_meta: { is_stale: false, fetched_at: '2026-05-19T13:42:00+00:00', sources_unavailable: [] },
  next_actions: [],
};

function dashboardCard(actionId) {
  const isDte = actionId === 'leg.dte_review';
  return {
    id: `${actionId}.${LEG_ID}`,
    action_id: actionId,
    priority: isDte ? 'P2' : 'P1',
    tone: isDte ? undefined : 'opportunity',
    title: isDte ? '21-day review' : 'Buy-to-close review',
    subject: { ticker: 'F', amount: '15C' },
    reason: 'Your management rule triggered for this leg.',
    cta: { label: 'Review buy-to-close', href: BTC_ROUTE, kind: 'link' },
    triggered_rules: [],
  };
}

function mockDashboard(page, card) {
  return page.route('**/api/dashboard', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ...DASHBOARD_BASE, next_actions: [card] }),
    }),
  );
}

// --- Tests: route renders + states -----------------------------------------

test.describe('BTC detail screen — route + states @e2e', () => {
  test('renders the populated page for a valid leg', async ({ page }) => {
    await mockBtcDetail(page, populatedPayload());
    await openBtcDetail(page);

    await expect(page.getByTestId('btc-detail-page')).toBeVisible();
    await expect(page.getByTestId('btc-detail-leg-header')).toContainText(
      'Buy-to-close review: F $15 C',
    );
    // The triggered rule pill names the user's rule, attributed.
    const pill = page.getByTestId('btc-detail-rule-pill');
    await expect(pill).toHaveAttribute('data-verdict', 'profit_take_review');
    await expect(pill).toContainText('profit-take rule');
  });

  test('renders the three content blocks: recommendation, economics, audit', async ({
    page,
  }) => {
    await mockBtcDetail(page, populatedPayload());
    await openBtcDetail(page);

    // (c) recommended action summary
    await expect(
      page.getByTestId('btc-detail-recommended-reasoning'),
    ).toContainText('profit-take rule triggered');
    // (b) BTC economics tiles
    await expect(
      page.getByTestId('btc-detail-economics-tile-cost-to-close'),
    ).toContainText('$15.72');
    await expect(
      page.getByTestId('btc-detail-economics-tile-credit'),
    ).toContainText('$38.34');
    // BRIDGE EDIT (issue #319): the 4th tile "% premium captured"
    // (btc-detail-economics-tile-pct-captured) was replaced by the honest
    // "Extrinsic % of mid" tile. The old assertion is removed here.
    await expect(
      page.getByTestId('btc-detail-economics-tile-extrinsic-pct'),
    ).toContainText('7%');
    await expect(
      page.getByTestId('btc-detail-economics-tile-est-pl'),
    ).toContainText('+$22.62');
    // (a) rule audit — Metric/Value/Rule/Triggered? rows for ALL rules
    await expect(page.getByTestId('btc-detail-rule-audit-table')).toBeVisible();
    for (const id of [
      'profit_review',
      'dte_review',
      'expiration_warning',
      'assignment_risk',
    ]) {
      await expect(
        page.getByTestId(`btc-detail-rule-audit-row-${id}`),
      ).toBeVisible();
    }
    // The governing rule's status cell reads "Yes".
    await expect(
      page.getByTestId('btc-detail-rule-audit-status-profit_review'),
    ).toContainText('Yes');
  });

  test('advice-framing — audit + pill attribute to the user, not the app', async ({
    page,
  }) => {
    await mockBtcDetail(page, populatedPayload());
    await openBtcDetail(page);

    await expect(page.getByTestId('btc-detail-rule-audit')).toContainText(
      'checked against your Management Triggers',
    );
    await expect(page.getByTestId('btc-detail-rule-pill')).toContainText(
      'Your',
    );
  });

  test('404 renders the leg-not-found EmptyState (not the error banner)', async ({
    page,
  }) => {
    await mockBtcDetail(page, { detail: 'Leg not found' }, 404);
    await openBtcDetail(page);

    await expect(page.getByTestId('btc-detail-not-found')).toBeVisible();
    await expect(page.getByTestId('btc-detail-not-found')).toContainText(
      'Leg not found',
    );
    // It must NOT be treated as a generic error.
    await expect(page.getByTestId('btc-detail-error')).toHaveCount(0);
    await expect(page.getByTestId('btc-detail-page')).toHaveCount(0);
  });

  test('a server error renders the retry banner', async ({ page }) => {
    await mockBtcDetail(
      page,
      { detail: 'Failed to load buy-to-close detail. Please try again.' },
      500,
    );
    await openBtcDetail(page);

    await expect(page.getByTestId('btc-detail-error')).toBeVisible();
    await expect(
      page.getByTestId('btc-detail-error').getByRole('button', { name: 'Retry' }),
    ).toBeVisible();
  });

  test('no-rule-triggered: economics + audit render, Buy-to-close CTA omitted', async ({
    page,
  }) => {
    await mockBtcDetail(page, noRulePayload());
    await openBtcDetail(page);

    await expect(page.getByTestId('btc-detail-no-rule')).toBeVisible();
    // Economics and audit still render fully.
    await expect(page.getByTestId('btc-detail-economics')).toBeVisible();
    await expect(page.getByTestId('btc-detail-rule-audit')).toBeVisible();
    // No closing verdict fired → no Buy-to-close CTA; journal link still shows.
    await expect(page.getByTestId('btc-detail-cta-close')).toHaveCount(0);
    await expect(page.getByTestId('btc-detail-cta-journal')).toBeVisible();
  });

  test('pricing-unavailable: em-dash tiles + "Pricing unavailable" badge', async ({
    page,
  }) => {
    await mockBtcDetail(page, pricingUnavailablePayload());
    await openBtcDetail(page);

    await expect(
      page.getByTestId('btc-detail-economics-stub-badge'),
    ).toBeVisible();
    await expect(
      page.getByTestId('btc-detail-economics-tile-cost-to-close'),
    ).toContainText('—');
    // Credit received still shows its real static value.
    await expect(
      page.getByTestId('btc-detail-economics-tile-credit'),
    ).toContainText('$61.00');
  });
});

// --- Tests: CTA navigation from the dashboard action cards ------------------

test.describe('BTC detail screen — reachable from dashboard card CTA @e2e', () => {
  test('"Review buy-to-close →" on a profit-take card navigates to the BTC route', async ({
    page,
  }) => {
    await mockDashboard(page, dashboardCard('leg.profit_take_review'));
    await mockBtcDetail(page, populatedPayload());

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    // The whole card is the CTA `<Link>` — its href is the BTC route.
    const cardEl = page.getByTestId(
      `next-actions-card-leg.profit_take_review.${LEG_ID}`,
    );
    await expect(cardEl).toBeVisible();
    await expect(cardEl).toContainText('Review buy-to-close');
    await expect(cardEl).toHaveAttribute('href', BTC_ROUTE);
    await cardEl.click();
    await page.waitForLoadState('networkidle');

    await expect(page).toHaveURL(new RegExp(`${BTC_ROUTE}$`));
    await expect(page.getByTestId('btc-detail-page')).toBeVisible();
    await expect(page.getByTestId('btc-detail-leg-header')).toContainText('F');
  });

  test('"Review buy-to-close →" on a DTE-review card also navigates to the BTC route', async ({
    page,
  }) => {
    await mockDashboard(page, dashboardCard('leg.dte_review'));
    await mockBtcDetail(page, populatedPayload({ verdict: 'dte_review' }));

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const cardEl = page.getByTestId(
      `next-actions-card-leg.dte_review.${LEG_ID}`,
    );
    await expect(cardEl).toBeVisible();
    await expect(cardEl).toHaveAttribute('href', BTC_ROUTE);
    await cardEl.click();
    await page.waitForLoadState('networkidle');

    await expect(page).toHaveURL(new RegExp(`${BTC_ROUTE}$`));
    await expect(page.getByTestId('btc-detail-page')).toBeVisible();
  });
});

// --- Tests: journal pre-fill via the "Buy to close" CTA ---------------------

const JOURNAL_POSITION = {
  id: POSITION_ID,
  ticker: 'F',
  shares: 100,
  strategy: 'cc',
  status: 'open',
  broker_cost_basis: 1500,
  adjusted_cost_basis: 1461.66,
  min_compliant_cc_strike: 15,
  total_premiums: 38.34,
  trades: [
    {
      id: LEG_ID,
      position_id: POSITION_ID,
      trade_type: 'sell_call',
      strike: 15.0,
      expiration: '2026-06-26',
      premium: 0.3834,
      fees: 0,
      quantity: 1,
      opened_at: '2026-04-01T10:00:00Z',
      closed_at: null,
      close_reason: null,
    },
  ],
};

async function mockJournalPositions(page, positions) {
  // The list endpoint (used by the positions table).
  await page.route('**/api/journal/positions', (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ positions }),
    });
  });
  // The single-position endpoint (used by selectPosition → TradeHistory).
  await page.route('**/api/journal/positions/*', (route) => {
    if (route.request().method() !== 'GET') return route.continue();
    const url = route.request().url();
    const found = positions.find((p) => url.endsWith(`/${p.id}`));
    if (!found) {
      return route.fulfill({
        status: 404,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Position not found' }),
      });
    }
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(found),
    });
  });
}

test.describe('BTC detail — journal close-leg pre-fill (issue #244) @e2e', () => {
  test('"Buy to close" CTA points at the close-leg journal deep-link', async ({
    page,
  }) => {
    await mockBtcDetail(page, populatedPayload());
    await openBtcDetail(page);

    const cta = page.getByTestId('btc-detail-cta-close');
    await expect(cta).toBeVisible();
    await expect(cta).toHaveAttribute(
      'href',
      `/journal?position=${POSITION_ID}&leg=${LEG_ID}&action=close-leg`,
    );
  });

  test('arriving at the close-leg deep-link pre-fills the inverse-close form', async ({
    page,
  }) => {
    await mockJournalPositions(page, [JOURNAL_POSITION]);
    await page.goto(
      `/journal?position=${POSITION_ID}&leg=${LEG_ID}&action=close-leg`,
    );
    await page.waitForLoadState('networkidle');

    // The trade form auto-opens, pre-filled with the inverse-close trade.
    const form = page.getByTestId('trade-entry-form');
    await expect(form).toBeVisible();
    // sell_call → buy_call_close.
    await expect(page.getByTestId('trade-entry-type')).toHaveValue(
      'buy_call_close',
    );
    await expect(page.getByTestId('trade-entry-strike')).toHaveValue('15');
    await expect(page.getByTestId('trade-entry-expiration')).toHaveValue(
      '2026-06-26',
    );
  });

  test('close-leg pre-fill applies only to the auto-opened form, not a later manual one', async ({
    page,
  }) => {
    await mockJournalPositions(page, [JOURNAL_POSITION]);
    await page.goto(
      `/journal?position=${POSITION_ID}&leg=${LEG_ID}&action=close-leg`,
    );
    await page.waitForLoadState('networkidle');

    // The auto-opened form is pre-filled with the inverse-close leg.
    await expect(page.getByTestId('trade-entry-form')).toBeVisible();
    await expect(page.getByTestId('trade-entry-type')).toHaveValue(
      'buy_call_close',
    );

    // Dismiss it, then manually re-open via the "Add Trade" button.
    await page.getByTestId('add-trade-btn').click();
    await expect(page.getByTestId('trade-entry-form')).toHaveCount(0);
    await page.getByTestId('add-trade-btn').click();

    // The manually-opened form must be blank — no stale buy-to-close values.
    await expect(page.getByTestId('trade-entry-form')).toBeVisible();
    await expect(page.getByTestId('trade-entry-type')).toHaveValue('sell_put');
    await expect(page.getByTestId('trade-entry-strike')).toHaveValue('');
    await expect(page.getByTestId('trade-entry-expiration')).toHaveValue('');
  });

  test('degrades gracefully when the leg param does not resolve', async ({
    page,
  }) => {
    await mockJournalPositions(page, [JOURNAL_POSITION]);
    await page.goto(
      `/journal?position=${POSITION_ID}&leg=no-such-leg&action=close-leg`,
    );
    await page.waitForLoadState('networkidle');

    // The journal opens on the position; no form auto-opens, no error.
    await expect(page.getByTestId('trade-history')).toBeVisible();
    await expect(page.getByTestId('trade-entry-form')).toHaveCount(0);
  });
});

// --- Tests: BTC Analysis panel (issue #319) --------------------------------

test.describe('BTC Analysis panel — decision math @e2e', () => {
  test('renders decomposition, breakeven, and ≥4-row scenario table for ITM fixture @e2e', async ({
    page,
  }) => {
    await mockBtcDetail(page, populatedPayload());
    await openBtcDetail(page);

    const panel = page.getByTestId('btc-analysis');
    await expect(panel).toBeVisible();
    // Section 1 — decomposition trio.
    await expect(page.getByTestId('btc-analysis-intrinsic')).toContainText(
      '$1.79',
    );
    await expect(page.getByTestId('btc-analysis-extrinsic')).toContainText(
      '$0.14',
    );
    await expect(page.getByTestId('btc-analysis-extrinsic-pct')).toContainText(
      '7%',
    );
    // Section 2 — breakeven line.
    await expect(page.getByTestId('btc-analysis-breakeven')).toContainText(
      '$16.43',
    );
    // Section 3 — ≥4-row scenario table.
    await expect(
      page.getByTestId('btc-analysis-scenario-table'),
    ).toBeVisible();
    for (let i = 0; i < 4; i += 1) {
      await expect(
        page.getByTestId(`btc-analysis-scenario-row-${i}`),
      ).toBeVisible();
    }
    // The up scenarios favor BTC; the down/flat favor assign.
    await expect(page.getByTestId('btc-analysis-scenario-row-0')).toContainText(
      'Assign wins',
    );
    await expect(page.getByTestId('btc-analysis-scenario-row-2')).toContainText(
      'BTC wins',
    );
  });

  test('breakeven line shows signed delta vs underlying @e2e', async ({
    page,
  }) => {
    await mockBtcDetail(page, populatedPayload());
    await openBtcDetail(page);

    const delta = page.getByTestId('btc-analysis-breakeven-delta');
    // Signed (−) + dollar literal + direction word, never NaN.
    await expect(delta).toContainText('-$0.14');
    await expect(delta).toContainText('below breakeven');
  });

  test('guidance copy explains breakeven intuition @e2e', async ({ page }) => {
    await mockBtcDetail(page, populatedPayload());
    await openBtcDetail(page);

    await expect(page.getByTestId('btc-analysis-guidance')).toContainText(
      'must rise above your BTC breakeven',
    );
    await expect(page.getByTestId('btc-analysis-guidance')).toContainText(
      'letting it assign keeps more',
    );
  });

  test('4th economics tile shows Extrinsic % of mid; raw %CAPT demoted to footnote @e2e', async ({
    page,
  }) => {
    await mockBtcDetail(page, populatedPayload());
    await openBtcDetail(page);

    // The replaced tile reads the honest extrinsic% signal.
    await expect(
      page.getByTestId('btc-detail-economics-tile-extrinsic-pct'),
    ).toContainText('Extrinsic % of mid');
    await expect(
      page.getByTestId('btc-detail-economics-tile-extrinsic-pct'),
    ).toContainText('7%');
    // The old misleading tile is gone.
    await expect(
      page.getByTestId('btc-detail-economics-tile-pct-captured'),
    ).toHaveCount(0);
    // captured_pct survives as a muted, labelled footnote.
    const note = page.getByTestId('btc-detail-economics-captured-raw-note');
    await expect(note).toBeVisible();
    await expect(note).toContainText('Premium captured (raw)');
    await expect(note).toContainText('59%');
  });

  test('degraded state shows badge + em-dash, never NaN @e2e', async ({
    page,
  }) => {
    await mockBtcDetail(page, pricingUnavailablePayload());
    await openBtcDetail(page);

    await expect(page.getByTestId('btc-analysis')).toBeVisible();
    await expect(
      page.getByTestId('btc-analysis-degraded-badge'),
    ).toBeVisible();
    // Decomposition figures show the em-dash, never NaN.
    await expect(page.getByTestId('btc-analysis-intrinsic')).toContainText('—');
    await expect(page.getByTestId('btc-analysis')).not.toContainText('NaN');
    // No scenario table when unavailable.
    await expect(
      page.getByTestId('btc-analysis-scenario-table'),
    ).toHaveCount(0);
  });
});
