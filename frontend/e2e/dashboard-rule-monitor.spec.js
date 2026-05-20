import { test, expect } from '@playwright/test';

/**
 * E2E for issue #240 — per-leg rule monitor + action cards.
 *
 * Covers AC:
 *   - ACTION column renders the rule-driven verdict (Hold / Review · 50% /
 *     Review · 21d / Close · exp / Close · ITM) with the spec §2.3 treatment.
 *   - Leg row is a `<button>` toggle; clicking expands an inline InspectPanel
 *     with the Metric/Value/Rule/Triggered? audit table + reasoning + CTAs.
 *   - Multi-open expansion — two panels can be open at once.
 *   - Quiet leg (verdict=hold) is still inspectable; no Buy-to-close CTA.
 *   - leg.profit_take_review card renders emerald + ✓ + [P1];
 *     leg.dte_review card renders slate + [P2].
 *   - Dead `#leg-{id}` deep link removed (issue #244) — a `#leg-` hash no
 *     longer auto-expands any row.
 *   - Degraded path — no live mid → % Capt `—`, DTE-based fallback verdict.
 *
 * Mirrors `dashboard-open-legs-card.spec.js` — same `mockDashboard()` +
 * `makeLeg()` fixture pattern.
 */

const BASE_PAYLOAD = {
  generated_at: '2026-05-18T13:42:00+00:00',
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
    open_legs: 4,
    open_legs_breakdown: { puts: 2, calls: 2 },
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
      id: 'pos-ford',
      ticker: 'F',
      shares: 100,
      strategy: 'wheel',
      adjusted_cost_basis: 1500.0,
      current_price: 15.5,
      notional: 1550.0,
      unrealized_pl: 0,
      open_legs_count: 1,
      wheel_status: 'Wheel',
      next_suggested_action: 'Review',
      pl_pct: 0,
      broker_cost_basis: 1500.0,
    },
  ],
  recent_activity: [],
  data_meta: {
    is_stale: false,
    fetched_at: '2026-05-18T13:42:00+00:00',
    sources_unavailable: [],
  },
  next_actions: [],
};

// Build the four-row triggered_rules payload, governed by `verdict`.
function makeTriggeredRules({ verdict, dte, capturedPct, moneyness }) {
  const dteValue = `${dte} d`;
  const captured =
    capturedPct == null ? '—' : `${Math.round(capturedPct * 100)}%`;
  const moneynessValue = moneyness ? moneyness.state : '—';
  const rows = [
    {
      rule_id: 'assignment_risk',
      metric_label: 'Assignment risk',
      value_display: moneynessValue,
      rule_display: 'Review at ≥ High',
      status: verdict === 'assignment' ? 'triggered' : 'no',
      is_governing: verdict === 'assignment',
      reasoning: null,
    },
    {
      rule_id: 'expiration_warning',
      metric_label: 'Days to expiration',
      value_display: dteValue,
      rule_display: 'Warn at ≤ 7 d',
      status:
        verdict === 'expiration'
          ? 'triggered'
          : dte > 7
            ? 'not_yet'
            : 'no',
      is_governing: verdict === 'expiration',
      reasoning: null,
    },
    {
      rule_id: 'profit_review',
      metric_label: 'Premium captured',
      value_display: captured,
      rule_display: 'Review at ≥ 50%',
      status:
        capturedPct == null
          ? 'no'
          : verdict === 'profit_take_review'
            ? 'triggered'
            : 'not_yet',
      is_governing: verdict === 'profit_take_review',
      reasoning: null,
    },
    {
      rule_id: 'dte_review',
      metric_label: 'Days to expiration',
      value_display: dteValue,
      rule_display: 'Review at ≤ 21 d',
      status:
        verdict === 'dte_review'
          ? 'triggered'
          : dte > 21
            ? 'not_yet'
            : 'triggered',
      is_governing: verdict === 'dte_review',
      reasoning: null,
    },
  ];
  const reasoning = {
    hold: 'No management rule has triggered for this leg yet.',
    profit_take_review: 'Your 50% profit-take rule triggered. This leg has captured 60% of its max premium.',
    dte_review: 'This leg is inside your 21-day review window. Your rule says: decide — hold, roll, or close.',
    expiration: 'Your expiration rule triggered — 5 days to expiration.',
    assignment: 'Your expiration rule triggered and this leg is ITM — 5 days to expiration with assignment risk.',
  }[verdict];
  rows.forEach((r) => {
    if (r.is_governing) r.reasoning = reasoning;
  });
  return { rows, reasoning };
}

const VERDICT_LABEL = {
  hold: 'Hold',
  profit_take_review: 'Review · 50%',
  dte_review: 'Review · 21d',
  expiration: 'Close · exp',
  assignment: 'Close · ITM',
};

function makeLeg(overrides = {}) {
  const verdict = overrides.verdict || 'hold';
  const dte = overrides.dte ?? 38;
  const capturedPct =
    overrides.capturedPct !== undefined ? overrides.capturedPct : 0.18;
  const moneyness =
    overrides.moneyness !== undefined
      ? overrides.moneyness
      : { state: 'OTM', distance_pct: 0.033, distance_dollars: 0.5 };
  const { rows, reasoning } = makeTriggeredRules({
    verdict,
    dte,
    capturedPct,
    moneyness,
  });
  return {
    id: overrides.id || 'leg-ford-15c',
    ticker: overrides.ticker || 'F',
    type: overrides.type || 'call',
    strike: overrides.strike ?? 15.0,
    expiration: overrides.expiration || '2026-06-26',
    dte,
    moneyness,
    position_id: overrides.position_id || 'pos-ford',
    profit_target_status:
      capturedPct == null
        ? { captured_pct: null, state: 'unknown' }
        : {
            captured_pct: capturedPct,
            state: verdict === 'profit_take_review' ? 'captured_50' : 'in_progress',
          },
    assignment_risk: overrides.assignment_risk || 'low',
    suggested_action: 'hold',
    earnings_in_window: false,
    verdict,
    verdict_label: VERDICT_LABEL[verdict],
    reasoning,
    triggered_rules: rows,
  };
}

function makeCard(overrides = {}) {
  const actionId = overrides.action_id || 'leg.profit_take_review';
  return {
    id: overrides.id || `${actionId}.leg-ford-15c`,
    action_id: actionId,
    priority: overrides.priority || 'P1',
    tone: overrides.tone,
    title: overrides.title || 'Buy-to-close review',
    subject: overrides.subject || { ticker: 'F', amount: '15C' },
    reason: overrides.reason || 'Your 50% profit-take rule triggered — 60% of max premium captured.',
    cta: {
      label: 'Review buy-to-close',
      href:
        overrides.href ||
        '/positions/pos-ford/legs/leg-ford-15c/btc',
      kind: 'link',
    },
    triggered_rules: overrides.triggered_rules || [],
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

test.describe('OpenLegsCard rule monitor — ACTION verdict column', () => {
  test('profit-take verdict renders "Review · 50%" emerald', async ({ page }) => {
    const leg = makeLeg({ verdict: 'profit_take_review', capturedPct: 0.6 });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [leg] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const action = page.getByTestId('dashboard-leg-row-action').first();
    await expect(action).toContainText('Review · 50%');
    const verdictEl = action.locator('[data-verdict="profit_take_review"]');
    await expect(verdictEl).toHaveClass(/emerald/);
  });

  test('dte-review verdict renders "Review · 21d" amber', async ({ page }) => {
    const leg = makeLeg({ verdict: 'dte_review', dte: 20, capturedPct: 0.31 });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [leg] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const action = page.getByTestId('dashboard-leg-row-action').first();
    await expect(action).toContainText('Review · 21d');
    await expect(action.locator('[data-verdict="dte_review"]')).toHaveClass(/amber/);
  });

  test('assignment verdict renders "Close · ITM" red with ⛔', async ({ page }) => {
    const leg = makeLeg({
      verdict: 'assignment',
      dte: 5,
      capturedPct: 0.44,
      moneyness: { state: 'ITM', distance_pct: 0.04, distance_dollars: 0.62 },
      assignment_risk: 'high',
    });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [leg] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const action = page.getByTestId('dashboard-leg-row-action').first();
    await expect(action).toContainText('Close · ITM');
    await expect(action).toContainText('⛔');
    await expect(action.locator('[data-verdict="assignment"]')).toHaveClass(/red/);
  });

  test('expiration verdict renders "Close · exp" red', async ({ page }) => {
    const leg = makeLeg({ verdict: 'expiration', dte: 5, capturedPct: 0.2 });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [leg] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const action = page.getByTestId('dashboard-leg-row-action').first();
    await expect(action).toContainText('Close · exp');
    await expect(action.locator('[data-verdict="expiration"]')).toHaveClass(/red/);
  });

  test('quiet leg renders neutral "Hold" verdict', async ({ page }) => {
    const leg = makeLeg({ verdict: 'hold', dte: 73, capturedPct: 0.18 });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [leg] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const action = page.getByTestId('dashboard-leg-row-action').first();
    await expect(action.locator('[data-verdict="hold"]')).toHaveText('Hold');
  });

  test('%CAPT and ACTION agree at threshold (state captured_50 → Review · 50%)', async ({ page }) => {
    const leg = makeLeg({ verdict: 'profit_take_review', capturedPct: 0.6 });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [leg] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    await expect(page.getByTestId('dashboard-leg-row-captured').first()).toContainText('60%');
    await expect(page.getByTestId('dashboard-leg-row-action').first()).toContainText('Review · 50%');
  });
});

test.describe('OpenLegsCard rule monitor — InspectPanel', () => {
  test('clicking a leg row expands the inspect panel', async ({ page }) => {
    const leg = makeLeg({ verdict: 'profit_take_review', capturedPct: 0.6 });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [leg] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const row = page.getByTestId('dashboard-leg-row').first();
    await expect(row).toHaveAttribute('aria-expanded', 'false');
    await row.click();
    await expect(row).toHaveAttribute('aria-expanded', 'true');
    await expect(page.getByTestId('dashboard-leg-inspect-leg-ford-15c')).toBeVisible();
  });

  test('inspect table renders four rule rows with tri-state status', async ({ page }) => {
    const leg = makeLeg({ verdict: 'profit_take_review', capturedPct: 0.6 });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [leg] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    await page.getByTestId('dashboard-leg-row').first().click();
    const id = 'leg-ford-15c';
    await expect(page.getByTestId(`dashboard-leg-inspect-table-${id}`)).toBeVisible();
    // Governing profit_review row shows ● Yes.
    const profitStatus = page.getByTestId(`dashboard-leg-inspect-status-${id}-profit_review`);
    await expect(profitStatus).toContainText('Yes');
    // Assignment row is non-firing — ○ No.
    const assignStatus = page.getByTestId(`dashboard-leg-inspect-status-${id}-assignment_risk`);
    await expect(assignStatus).toContainText('No');
    // The dte_review row trends toward the window — Not yet.
    const dteStatus = page.getByTestId(`dashboard-leg-inspect-status-${id}-dte_review`);
    await expect(dteStatus).toContainText('Not yet');
  });

  test('inspect panel reasoning is attributed to the user ruleset', async ({ page }) => {
    const leg = makeLeg({ verdict: 'profit_take_review', capturedPct: 0.6 });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [leg] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    await page.getByTestId('dashboard-leg-row').first().click();
    const reasoning = page.getByTestId('dashboard-leg-inspect-reasoning-leg-ford-15c');
    await expect(reasoning).toContainText('Your');
    await expect(reasoning).toContainText('rule triggered');
  });

  test('Buy-to-close CTA shown for a closing verdict', async ({ page }) => {
    const leg = makeLeg({ verdict: 'profit_take_review', capturedPct: 0.6 });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [leg] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    await page.getByTestId('dashboard-leg-row').first().click();
    const closeCta = page.getByTestId('dashboard-leg-inspect-cta-close-leg-ford-15c');
    await expect(closeCta).toBeVisible();
    await expect(closeCta).toHaveAttribute(
      'href',
      '/journal?position=pos-ford&action=close-leg'
    );
    await expect(
      page.getByTestId('dashboard-leg-inspect-cta-journal-leg-ford-15c')
    ).toBeVisible();
  });

  test('quiet leg is inspectable but has no Buy-to-close CTA', async ({ page }) => {
    const leg = makeLeg({ verdict: 'hold', dte: 73, capturedPct: 0.18 });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [leg] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    await page.getByTestId('dashboard-leg-row').first().click();
    await expect(page.getByTestId('dashboard-leg-inspect-leg-ford-15c')).toBeVisible();
    await expect(
      page.getByTestId('dashboard-leg-inspect-reasoning-leg-ford-15c')
    ).toContainText('No management rule has triggered');
    await expect(
      page.getByTestId('dashboard-leg-inspect-cta-close-leg-ford-15c')
    ).toHaveCount(0);
  });

  test('multiple rows can be expanded at once (multi-open)', async ({ page }) => {
    const legA = makeLeg({ id: 'leg-a', ticker: 'F', verdict: 'profit_take_review', capturedPct: 0.6 });
    const legB = makeLeg({
      id: 'leg-b',
      ticker: 'AAPL',
      strike: 190,
      type: 'put',
      verdict: 'dte_review',
      dte: 20,
      capturedPct: 0.31,
    });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [legA, legB] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const rows = page.getByTestId('dashboard-leg-row');
    await rows.nth(0).click();
    await rows.nth(1).click();
    await expect(page.getByTestId('dashboard-leg-inspect-leg-a')).toBeVisible();
    await expect(page.getByTestId('dashboard-leg-inspect-leg-b')).toBeVisible();
  });
});

test.describe('OpenLegsCard rule monitor — degraded path', () => {
  test('no live mid → % Capt shows — and verdict falls back to DTE rule', async ({ page }) => {
    const leg = makeLeg({
      id: 'leg-nvda',
      ticker: 'NVDA',
      type: 'put',
      strike: 120,
      verdict: 'dte_review',
      dte: 12,
      capturedPct: null,
    });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [leg] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    await expect(page.getByTestId('dashboard-leg-row-captured').first()).toContainText('—');
    await expect(page.getByTestId('dashboard-leg-row-action').first()).toContainText('Review · 21d');

    await page.getByTestId('dashboard-leg-row').first().click();
    const profitStatus = page.getByTestId('dashboard-leg-inspect-status-leg-nvda-profit_review');
    await expect(profitStatus).toContainText('No');
  });
});

test.describe('NextActionCard — rule-monitor cards', () => {
  test('leg.profit_take_review card renders emerald, ✓, [P1]', async ({ page }) => {
    const card = makeCard({ action_id: 'leg.profit_take_review', tone: 'opportunity', priority: 'P1' });
    await mockDashboard(page, {
      ...BASE_PAYLOAD,
      open_legs: [makeLeg({ verdict: 'profit_take_review', capturedPct: 0.6 })],
      next_actions: [card],
    });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const cardEl = page.getByTestId('next-actions-card-leg.profit_take_review.leg-ford-15c');
    await expect(cardEl).toBeVisible();
    await expect(cardEl).toHaveClass(/emerald/);
    await expect(cardEl).toContainText('✓');
    await expect(cardEl).toContainText('[P1]');
  });

  test('leg.dte_review card renders slate, [P2]', async ({ page }) => {
    const card = makeCard({
      action_id: 'leg.dte_review',
      id: 'leg.dte_review.leg-aapl',
      priority: 'P2',
      title: '21-day review',
      tone: undefined,
      subject: { ticker: 'AAPL', amount: '190P' },
      reason: '20 days to expiration — your review window. Decide: hold, roll, or close.',
      href: '/positions/pos-aapl/legs/leg-aapl/btc',
    });
    await mockDashboard(page, {
      ...BASE_PAYLOAD,
      open_legs: [makeLeg({ id: 'leg-aapl', verdict: 'dte_review', dte: 20, capturedPct: 0.31 })],
      next_actions: [card],
    });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const cardEl = page.getByTestId('next-actions-card-leg.dte_review.leg-aapl');
    await expect(cardEl).toBeVisible();
    await expect(cardEl).toContainText('[P2]');
    await expect(cardEl).not.toHaveClass(/emerald/);
  });
});

test.describe('OpenLegsCard — dead #leg hash deep link removed (issue #244)', () => {
  test('navigating to /dashboard#leg-{id} does NOT auto-expand any row', async ({
    page,
  }) => {
    // Issue #244 removed the dead `#leg-{id}` deep-link. The card CTA now
    // navigates to the dedicated BTC detail screen instead. Landing on the
    // dashboard with a `#leg-` hash must leave every inspect panel collapsed.
    const legA = makeLeg({ id: 'leg-a', ticker: 'F', verdict: 'hold', dte: 73 });
    const legB = makeLeg({
      id: 'leg-b',
      ticker: 'AAPL',
      strike: 190,
      type: 'put',
      verdict: 'profit_take_review',
      capturedPct: 0.6,
    });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [legA, legB] });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard#leg-leg-b');
    await page.waitForLoadState('networkidle');

    // Both rows render — and NEITHER inspect panel is auto-expanded.
    await expect(page.getByTestId('dashboard-leg-row').first()).toBeVisible();
    await expect(page.getByTestId('dashboard-leg-inspect-leg-a')).toHaveCount(0);
    await expect(page.getByTestId('dashboard-leg-inspect-leg-b')).toHaveCount(0);
  });

  test('a #leg hash never crashes the dashboard', async ({ page }) => {
    // The hash-reading code (and its decodeURIComponent throw path) is gone.
    // Any `#leg-` hash — even a malformed one — is now inert.
    const leg = makeLeg({ id: 'leg-a', ticker: 'F', verdict: 'hold', dte: 73 });
    await mockDashboard(page, { ...BASE_PAYLOAD, open_legs: [leg] });

    const pageErrors = [];
    page.on('pageerror', (err) => pageErrors.push(err));

    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/dashboard#leg-%FF');
    await page.waitForLoadState('networkidle');

    await expect(page.getByTestId('dashboard-page')).toBeVisible();
    await expect(page.getByTestId('dashboard-leg-row').first()).toBeVisible();
    await expect(page.getByTestId('dashboard-leg-inspect-leg-a')).toHaveCount(0);
    expect(pageErrors).toHaveLength(0);
  });
});
