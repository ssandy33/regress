import { test, expect } from '@playwright/test';

/**
 * E2E for issue #182 — Recovery Plan engine + recommendation layer.
 *
 * Covers the issue's Tests section:
 *   - flagged position → open Recovery Plan → 3-4 path cards render with values
 *   - "Suggested fit" banner renders with the label + ≥2 "Why this fits" bullets
 *   - expand "Inspect scoring" → full criterion × path matrix visible
 *   - suppressed-card rendering (de-emphasized, suppression reason inline)
 *   - disclaimer visible on the panel
 *   - "No clear best fit" degradation state (driven by a route-intercept fixture)
 *
 * The Recovery Plan endpoint is `POST /api/positions/{id}/recovery-plan`. Every
 * test mocks it at the route level — no live backend or Schwab quote required.
 */

const DISCLAIMER =
  'This is a fit recommendation based on your configured preferences and stated assumptions. It is not investment advice, a price prediction, or a trade execution suggestion.';

const POSITION_ID = 'pos-sofi';

// --- Fixture builders -------------------------------------------------------

function positionSummary() {
  return {
    id: POSITION_ID,
    ticker: 'SOFI',
    shares: 200,
    adjusted_cost_basis: 7800.0,
    current_price: 23.76,
    unrealized_pl: -3048.0,
    pl_pct: -0.39,
  };
}

function assumptions() {
  return [
    {
      label: 'Premium rate (Wheel)',
      value: '1.5% / month',
      source: 'V0.5.8 heuristic (#183 V0.7)',
    },
    {
      label: 'Target yield (Sell & redeploy)',
      value: '12%',
      source: 'Settings → OKRs',
    },
    {
      label: 'Sizing cap (Average down)',
      value: '$5,000',
      // The sizing cap is a Trading Rule (issue #235), not an OKR.
      source: 'Settings → Trading Rules',
    },
    {
      label: 'Strategy preference',
      value: 'Not set',
      source: 'Settings → OKRs (V0.6)',
    },
    { label: 'Current price', value: '$23.76', source: 'Schwab quote' },
    {
      label: 'Tax / wash sale',
      value: 'Not modeled',
      source: 'User responsibility',
    },
  ];
}

function eligiblePaths() {
  return [
    {
      path_id: 'sell-redeploy',
      label: 'Sell & redeploy',
      eligibility: 'eligible',
      suppression_reason: null,
      capital_tied_up: 0,
      months_to_breakeven: { best: 5, expected: 6, worst: 9 },
      opportunity_cost_vs_baseline: 0,
      assumptions: ['Redeploy freed capital into a fresh CSP at 12% target yield.'],
      narration: null,
    },
    {
      path_id: 'wheel-cc',
      label: 'Wheel covered calls',
      eligibility: 'eligible',
      suppression_reason: null,
      capital_tied_up: 0,
      months_to_breakeven: { best: 8, expected: 11, worst: 16 },
      opportunity_cost_vs_baseline: 200,
      assumptions: ['Assumes 1.5%/month premium on the share count (V0.5.8 heuristic).'],
      narration: null,
    },
    {
      path_id: 'hold-monitor',
      label: 'Hold & monitor',
      eligibility: 'eligible',
      suppression_reason: null,
      capital_tied_up: 0,
      months_to_breakeven: { best: null, expected: null, worst: null },
      opportunity_cost_vs_baseline: 800,
      assumptions: ['No action taken — set price alerts at your chosen thresholds.'],
      narration: null,
    },
  ];
}

function suppressedAverageDown() {
  return {
    path_id: 'average-down',
    label: 'Average down',
    eligibility: 'suppressed',
    suppression_reason: 'Exceeds per-position sizing cap ($4,752 vs $5,000 — would breach)',
    capital_tied_up: null,
    months_to_breakeven: { best: null, expected: null, worst: null },
    opportunity_cost_vs_baseline: null,
    assumptions: [],
    narration: null,
  };
}

// Issue #237: an *eligible* average-down path that carries a real
// `months_to_breakeven` projection (premium-grind methodology) instead of
// the suppressed null range. The frontend must render the computed value,
// not the `—` placeholder.
function eligibleAverageDown() {
  return {
    path_id: 'average-down',
    label: 'Average down',
    eligibility: 'eligible',
    suppression_reason: null,
    capital_tied_up: 4600.0,
    months_to_breakeven: { best: 100, expected: 125, worst: 163 },
    opportunity_cost_vs_baseline: 144.0,
    assumptions: [
      'Adds $800 at $8.00/share — new basis $23 per share.',
      'Within $5,000 sizing cap.',
      'Breakeven projects 1.5%/month wheel-CC premium on the doubled position against the remaining loss.',
    ],
    narration: null,
  };
}

function pathScores() {
  return [
    {
      criterion: 'fastest_breakeven',
      weight: 3,
      ranking: [
        { path_id: 'sell-redeploy', raw_value: 6, points: 3, rank: 1 },
        { path_id: 'wheel-cc', raw_value: 11, points: 0, rank: 2 },
        { path_id: 'hold-monitor', raw_value: null, points: 0, rank: 3 },
      ],
    },
    {
      criterion: 'lowest_additional_capital',
      weight: 3,
      ranking: [
        { path_id: 'sell-redeploy', raw_value: 0, points: 3, rank: 1 },
        { path_id: 'wheel-cc', raw_value: 0, points: 3, rank: 1 },
        { path_id: 'hold-monitor', raw_value: 0, points: 3, rank: 1 },
      ],
    },
    {
      criterion: 'lowest_opportunity_cost',
      weight: 2,
      ranking: [
        { path_id: 'sell-redeploy', raw_value: 0, points: 2, rank: 1 },
        { path_id: 'wheel-cc', raw_value: 200, points: 0, rank: 2 },
        { path_id: 'hold-monitor', raw_value: 800, points: 0, rank: 3 },
      ],
    },
  ];
}

// Populated payload with a clear recommendation (sell-redeploy wins).
function populatedPayload() {
  return {
    position_id: POSITION_ID,
    as_of: '2026-05-15T14:32:00+00:00',
    state: 'populated',
    position: positionSummary(),
    inputs: {
      current_price: 23.76,
      cost_basis: 7800.0,
      shares: 200,
      okr: {
        target_yield: 0.12,
        sizing_cap_pct: 25.0,
        sizing_cap_account: null,
        total_capital: 20000.0,
        strategy_preference: null,
      },
    },
    paths: [...eligiblePaths(), suppressedAverageDown()],
    recommendation: {
      recommended_path_id: 'sell-redeploy',
      recommendation_label: 'Best fit on capital efficiency and breakeven: Sell & redeploy',
      recommendation_reasons: [
        'Fastest expected breakeven (6 months vs 11 for the next option)',
        'Lowest additional capital required ($0)',
        'Lowest opportunity cost vs baseline ($0)',
      ],
      ranked_paths: [
        { path_id: 'sell-redeploy', score: 8, rank: 1, suppression_reason: null },
        { path_id: 'wheel-cc', score: 3, rank: 2, suppression_reason: null },
        { path_id: 'hold-monitor', score: 3, rank: 3, suppression_reason: null },
        {
          path_id: 'average-down',
          score: null,
          rank: null,
          suppression_reason:
            'Exceeds per-position sizing cap ($4,752 vs $5,000 — would breach)',
        },
      ],
      path_scores: pathScores(),
      tie_epsilon: 1.0,
      disclaimer: DISCLAIMER,
    },
    assumptions: assumptions(),
    disclaimer: DISCLAIMER,
  };
}

// Degradation payload: top two eligible paths tie within tie_epsilon.
function noClearBestFitPayload() {
  const base = populatedPayload();
  base.recommendation = {
    recommended_path_id: null,
    recommendation_label: 'No clear best fit',
    recommendation_reasons: [],
    ranked_paths: [
      { path_id: 'sell-redeploy', score: 6, rank: 1, suppression_reason: null },
      { path_id: 'wheel-cc', score: 6, rank: 2, suppression_reason: null },
      { path_id: 'hold-monitor', score: 3, rank: 3, suppression_reason: null },
      {
        path_id: 'average-down',
        score: null,
        rank: null,
        suppression_reason:
          'Exceeds per-position sizing cap ($4,752 vs $5,000 — would breach)',
      },
    ],
    path_scores: pathScores(),
    tie_epsilon: 1.0,
    disclaimer: DISCLAIMER,
  };
  return base;
}

// no-eligible-path payload: every path is suppressed by the sizing cap, so
// the banner renders the amber "Adjust caps →" CTA (issue #235 routes it at
// the Settings → Trading Rules tab).
function noEligiblePathPayload() {
  const base = populatedPayload();
  base.recommendation = {
    recommended_path_id: null,
    recommendation_label: 'No eligible path under current sizing rules',
    recommendation_reasons: [],
    ranked_paths: [
      {
        path_id: 'average-down',
        score: null,
        rank: null,
        suppression_reason:
          'Exceeds per-position sizing cap ($4,752 vs $5,000 — would breach)',
      },
    ],
    path_scores: pathScores(),
    tie_epsilon: 1.0,
    disclaimer: DISCLAIMER,
  };
  return base;
}

// Issue #237: payload whose average-down path clears the sizing-cap gate and
// therefore carries a computed `months_to_breakeven`. Swaps the suppressed
// average-down fixture for the eligible one; the recommendation block keeps a
// ranked entry for average-down so the card renders fully.
function eligibleAverageDownPayload() {
  const base = populatedPayload();
  base.paths = [...eligiblePaths(), eligibleAverageDown()];
  base.recommendation = {
    ...base.recommendation,
    ranked_paths: [
      { path_id: 'sell-redeploy', score: 8, rank: 1, suppression_reason: null },
      { path_id: 'wheel-cc', score: 3, rank: 2, suppression_reason: null },
      { path_id: 'hold-monitor', score: 3, rank: 3, suppression_reason: null },
      { path_id: 'average-down', score: 3, rank: 4, suppression_reason: null },
    ],
  };
  return base;
}

// not-flagged: position recovered above the review threshold.
function notFlaggedPayload() {
  return {
    position_id: POSITION_ID,
    as_of: '2026-05-15T14:32:00+00:00',
    state: 'not-flagged',
    position: {
      ...positionSummary(),
      unrealized_pl: 120.0,
      pl_pct: 0.015,
    },
    inputs: null,
    paths: [],
    recommendation: null,
    assumptions: [],
    disclaimer: DISCLAIMER,
  };
}

function mockRecoveryPlan(page, payload, status = 200) {
  return page.route(`**/api/positions/${POSITION_ID}/recovery-plan`, (route) =>
    route.fulfill({
      status,
      contentType: 'application/json',
      body: JSON.stringify(payload),
    }),
  );
}

async function openRecoveryPlan(page) {
  await page.goto(`/positions/${POSITION_ID}/recovery`);
  await page.waitForLoadState('networkidle');
}

// --- Tests ------------------------------------------------------------------

test.describe('Recovery Plan panel', () => {
  test('flagged position renders 3-4 path cards with values', async ({ page }) => {
    await mockRecoveryPlan(page, populatedPayload());
    await openRecoveryPlan(page);

    await expect(page.getByTestId('recovery-plan-page')).toBeVisible();

    const grid = page.getByTestId('recovery-path-grid');
    await expect(grid).toBeVisible();

    // All four paths render (3 eligible + 1 suppressed).
    await expect(page.getByTestId('recovery-path-card-sell-redeploy')).toBeVisible();
    await expect(page.getByTestId('recovery-path-card-wheel-cc')).toBeVisible();
    await expect(page.getByTestId('recovery-path-card-hold-monitor')).toBeVisible();
    await expect(page.getByTestId('recovery-path-card-average-down')).toBeVisible();

    // 3-4 path cards in total. The per-card data-testid is `recovery-path-card-{slug}`;
    // nested testids (e.g. `-capital`) extend it, so match `<article>` cards
    // by their `data-eligibility` attribute to avoid double-counting.
    const cardCount = await page
      .locator('article[data-testid^="recovery-path-card-"]')
      .count();
    expect(cardCount).toBeGreaterThanOrEqual(3);
    expect(cardCount).toBeLessThanOrEqual(4);

    // Eligible cards show their computed values, not placeholders.
    await expect(
      page.getByTestId('recovery-path-card-wheel-cc-capital'),
    ).toContainText('$0');
    await expect(
      page.getByTestId('recovery-path-card-wheel-cc-breakeven-expected'),
    ).toContainText('11 mo');
    await expect(
      page.getByTestId('recovery-path-card-wheel-cc-opp-cost'),
    ).toContainText('$200');

    // The reserved V0.6 narration placeholder is present (not omitted).
    await expect(page.getByTestId('recovery-narration-wheel-cc')).toBeAttached();
  });

  test('"Suggested fit" banner renders the label + ≥2 "Why this fits" bullets', async ({
    page,
  }) => {
    await mockRecoveryPlan(page, populatedPayload());
    await openRecoveryPlan(page);

    const banner = page.getByTestId('recovery-recommendation-banner');
    await expect(banner).toBeVisible();
    await expect(banner).toHaveAttribute('data-state', 'recommended');

    await expect(page.getByTestId('recovery-recommendation-label')).toContainText(
      'Best fit on capital efficiency and breakeven: Sell & redeploy',
    );

    const reasons = page.getByTestId('recovery-recommendation-reasons').locator('li');
    expect(await reasons.count()).toBeGreaterThanOrEqual(2);
    await expect(reasons.first()).toContainText('Fastest expected breakeven');
  });

  test('recommended card is emphasized; suppressed card is de-emphasized with reason inline', async ({
    page,
  }) => {
    await mockRecoveryPlan(page, populatedPayload());
    await openRecoveryPlan(page);

    const recommended = page.getByTestId('recovery-path-card-sell-redeploy');
    await expect(recommended).toHaveAttribute('data-recommended', 'true');
    await expect(
      page.getByTestId('recovery-path-card-sell-redeploy-recommended-badge'),
    ).toBeVisible();

    const suppressed = page.getByTestId('recovery-path-card-average-down');
    await expect(suppressed).toHaveAttribute('data-eligibility', 'suppressed');
    await expect(
      page.getByTestId('recovery-path-card-average-down-suppression'),
    ).toContainText('Exceeds per-position sizing cap');
  });

  test('"Inspect scoring" expands the full criterion × path matrix', async ({ page }) => {
    await mockRecoveryPlan(page, populatedPayload());
    await openRecoveryPlan(page);

    const matrix = page.getByTestId('recovery-scoring-matrix');
    await expect(matrix).toBeVisible();
    // Collapsed by default (locked decision Q1).
    await expect(matrix).not.toHaveJSProperty('open', true);

    await page.getByTestId('recovery-scoring-matrix-summary').click();
    await expect(matrix).toHaveJSProperty('open', true);

    // One row per criterion.
    await expect(
      page.getByTestId('recovery-scoring-row-fastest-breakeven'),
    ).toBeVisible();
    await expect(
      page.getByTestId('recovery-scoring-row-lowest-additional-capital'),
    ).toBeVisible();
    await expect(
      page.getByTestId('recovery-scoring-row-lowest-opportunity-cost'),
    ).toBeVisible();

    // A cell per eligible path carries raw value + points.
    await expect(
      page.getByTestId('recovery-scoring-cell-fastest-breakeven-sell-redeploy'),
    ).toContainText('3 pts');

    // Suppressed paths appear in the footer, not as a column.
    await expect(
      page.getByTestId('recovery-scoring-suppressed-average-down'),
    ).toContainText('Exceeds per-position sizing cap');
  });

  test('disclaimer is rendered persistently on the panel', async ({ page }) => {
    await mockRecoveryPlan(page, populatedPayload());
    await openRecoveryPlan(page);

    const disclaimer = page.getByTestId('recovery-disclaimer-text');
    await expect(disclaimer).toBeVisible();
    await expect(disclaimer).toHaveText(DISCLAIMER);
  });

  test('every assumption is visible in the assumptions panel', async ({ page }) => {
    await mockRecoveryPlan(page, populatedPayload());
    await openRecoveryPlan(page);

    const panel = page.getByTestId('recovery-assumptions-panel');
    await expect(panel).toBeVisible();

    // The premium-rate, target-yield, sizing-cap and strategy-preference
    // assumptions are all surfaced (not buried).
    await expect(panel).toContainText('1.5% / month');
    await expect(panel).toContainText('12%');
    await expect(panel).toContainText('$5,000');
    await expect(panel).toContainText('Strategy preference');
  });

  test('"No clear best fit" degradation state still renders the ranked paths', async ({
    page,
  }) => {
    await mockRecoveryPlan(page, noClearBestFitPayload());
    await openRecoveryPlan(page);

    const banner = page.getByTestId('recovery-recommendation-banner');
    await expect(banner).toHaveAttribute('data-state', 'no-clear-best-fit');
    await expect(page.getByTestId('recovery-recommendation-label')).toContainText(
      'No clear best fit',
    );

    // In the degradation state the banner intentionally has no templated
    // `recommendation_reasons` (fixture leaves it `[]`). Instead it renders
    // the top-two `ranked_paths` in the same `recovery-recommendation-reasons`
    // list so the user still sees the close call. Assert those two entries.
    const reasons = page.getByTestId('recovery-recommendation-reasons').locator('li');
    expect(await reasons.count()).toBe(2);
    await expect(reasons.first()).toContainText('Sell & redeploy');
    await expect(reasons.nth(1)).toContainText('Wheel covered calls');

    // The path cards still render; none carries the recommended badge.
    await expect(page.getByTestId('recovery-path-grid')).toBeVisible();
    await expect(
      page.locator('[data-testid$="-recommended-badge"]'),
    ).toHaveCount(0);

    // The scoring matrix is still available for manual audit.
    await expect(page.getByTestId('recovery-scoring-matrix')).toBeVisible();
  });

  test('not-flagged position renders the empty state instead of the panel', async ({
    page,
  }) => {
    await mockRecoveryPlan(page, notFlaggedPayload());
    await openRecoveryPlan(page);

    await expect(page.getByTestId('recovery-plan-not-flagged')).toBeVisible();
    await expect(page.getByTestId('recovery-recommendation-banner')).toHaveCount(0);
  });

  test('backend error surfaces a retry affordance', async ({ page }) => {
    await mockRecoveryPlan(
      page,
      { detail: 'Failed to build recovery plan. Please try again.' },
      500,
    );
    await openRecoveryPlan(page);

    await expect(page.getByTestId('recovery-plan-error')).toBeVisible();
    await expect(page.getByTestId('recovery-plan-error')).toContainText(
      'Failed to build recovery plan',
    );
  });

  test('sizing-cap suppression CTA routes to Settings → Trading Rules', async ({
    page,
  }) => {
    // Issue #235 Bug 2: the suppressed average-down card's "Adjust cap →"
    // CTA must route to /settings?tab=rules, never the dead /settings#okrs.
    await mockRecoveryPlan(page, populatedPayload());
    await openRecoveryPlan(page);

    const cta = page.getByTestId('recovery-path-card-average-down-suppression-cta');
    await expect(cta).toBeVisible();
    await expect(cta).toContainText('Adjust cap');
    await expect(cta).toHaveAttribute('href', '/settings?tab=rules');
    const href = await cta.getAttribute('href');
    expect(href).not.toContain('#okrs');
  });

  test('no-eligible-path banner CTA routes to Settings → Trading Rules', async ({
    page,
  }) => {
    // Issue #235 Bug 2: the amber banner's "Adjust caps →" CTA points at the
    // Trading Rules tab — caps are Trading Rules, not OKRs.
    await mockRecoveryPlan(page, noEligiblePathPayload());
    await openRecoveryPlan(page);

    const banner = page.getByTestId('recovery-recommendation-banner');
    await expect(banner).toHaveAttribute('data-state', 'no-eligible-path');
    await expect(banner).toContainText('Settings → Trading Rules');

    const cta = page.getByTestId('recovery-recommendation-adjust-caps');
    await expect(cta).toBeVisible();
    await expect(cta).toHaveAttribute('href', '/settings?tab=rules');
    const href = await cta.getAttribute('href');
    expect(href).not.toContain('#okrs');
  });

  test('average-down card shows a computed breakeven, not —', async ({ page }) => {
    // Issue #237: when the average-down path clears the sizing-cap gate it now
    // carries a real `months_to_breakeven` projection. The card's
    // breakeven-expected row must render the computed "<n> mo" value, never
    // the `formatMonths(null)` → `—` placeholder.
    await mockRecoveryPlan(page, eligibleAverageDownPayload());
    await openRecoveryPlan(page);

    const card = page.getByTestId('recovery-path-card-average-down');
    await expect(card).toBeVisible();
    await expect(card).toHaveAttribute('data-eligibility', 'eligible');

    const breakevenExpected = page.getByTestId(
      'recovery-path-card-average-down-breakeven-expected',
    );
    await expect(breakevenExpected).toBeVisible();
    // The eligible fixture projects expected = 125 months.
    await expect(breakevenExpected).toContainText('125 mo');
    await expect(breakevenExpected).not.toContainText('—');
  });

  test('assumptions panel attributes the sizing cap to Trading Rules', async ({
    page,
  }) => {
    // Issue #235 Bug 2: the Sizing-cap assumption row reads "Settings →
    // Trading Rules"; the target-yield row stays attributed to OKRs.
    await mockRecoveryPlan(page, populatedPayload());
    await openRecoveryPlan(page);

    const panel = page.getByTestId('recovery-assumptions-panel');
    await expect(panel).toBeVisible();
    await expect(panel).toContainText('Settings → Trading Rules');
    // Target yield is a genuine OKR — still attributed to OKRs.
    await expect(panel).toContainText('Settings → OKRs');
  });

  // Manual AC (CLAUDE.md — document non-automatable steps as a skipped test).
  // The issue's PR test plan includes a manual visual review of the populated
  // panel. Layout/visual fidelity is not asserted here; the structural,
  // copy, and state-machine ACs above are the automated contract.
  test.skip('manual: visual review of the populated panel layout', () => {
    // Intentionally skipped — visual fidelity is verified by hand against the
    // design intent before merge. Not automatable in Playwright assertions.
  });
});

// ---------------------------------------------------------------------------
// Issue #207 — Target Yield CTA + Sell & redeploy populated metrics.
//
// Append-only block (self-contained fixture builders included) so the sibling
// #237 PR, which also appends to this file, resolves only a trivial conflict.
// ---------------------------------------------------------------------------

test.describe('Recovery Plan — target yield (issue #207)', () => {
  /** A payload where Sell & redeploy is suppressed for an unset target yield —
   * the exact state the recovery "Set target yield →" CTA exists to fix. */
  function targetYieldSuppressedPayload() {
    const base = populatedPayload();
    base.inputs.okr.target_yield = null;
    base.paths = base.paths.map((p) =>
      p.path_id === 'sell-redeploy'
        ? {
            ...p,
            eligibility: 'suppressed',
            suppression_reason: 'Target yield not configured',
            capital_tied_up: null,
            months_to_breakeven: { best: null, expected: null, worst: null },
            opportunity_cost_vs_baseline: null,
          }
        : p,
    );
    base.recommendation.recommended_path_id = 'wheel-cc';
    base.recommendation.ranked_paths = base.recommendation.ranked_paths.map(
      (r) =>
        r.path_id === 'sell-redeploy'
          ? { ...r, score: null, rank: null, suppression_reason: 'Target yield not configured' }
          : r,
    );
    return base;
  }

  test('the "Set target yield →" CTA routes to Settings → Trading Objectives', async ({
    page,
  }) => {
    // Issue #207: the suppressed Sell & redeploy card's CTA must route to
    // /settings?tab=objectives — never the dead /settings#okrs anchor.
    await mockRecoveryPlan(page, targetYieldSuppressedPayload());
    await openRecoveryPlan(page);

    const cta = page.getByTestId(
      'recovery-path-card-sell-redeploy-suppression-cta',
    );
    await expect(cta).toBeVisible();
    await expect(cta).toContainText('Set target yield');
    await expect(cta).toHaveAttribute('href', '/settings?tab=objectives');

    // The old dead anchor must be gone.
    const href = await cta.getAttribute('href');
    expect(href).not.toContain('#okrs');
  });

  test('the populated Sell & redeploy card renders computed capital / breakeven / opportunity cost (AC3)', async ({
    page,
  }) => {
    // Issue #207 AC3: once a target yield is set, the Sell & redeploy path is
    // eligible and its three metrics compute — none of them the suppressed
    // "—" placeholder. populatedPayload()'s sell-redeploy is eligible.
    await mockRecoveryPlan(page, populatedPayload());
    await openRecoveryPlan(page);

    const capital = page.getByTestId('recovery-path-card-sell-redeploy-capital');
    const breakeven = page.getByTestId(
      'recovery-path-card-sell-redeploy-breakeven-expected',
    );
    const oppCost = page.getByTestId(
      'recovery-path-card-sell-redeploy-opp-cost',
    );

    await expect(capital).toBeVisible();
    await expect(breakeven).toBeVisible();
    await expect(oppCost).toBeVisible();

    // None of the three renders the suppressed-state em-dash placeholder.
    await expect(capital).not.toHaveText('—');
    await expect(breakeven).not.toHaveText('—');
    await expect(oppCost).not.toHaveText('—');

    // The computed values from the eligible fixture are surfaced.
    await expect(capital).toContainText('$0');
    await expect(breakeven).toContainText('6 mo');
  });
});
