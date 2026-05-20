import { test, expect } from '@playwright/test';

/**
 * Settings → Trading Rules section (issue #158).
 *
 * Covers the issue's automated-coverage ACs:
 *  - field renders with the correct label + helper text;
 *  - the whole-percent convention is preserved 1:1 (no fraction conversion);
 *  - boundary validation triggers (`min < max`, ranges, delta 0–1);
 *  - an Optional/unset field renders empty and saves as `null` — not `0`;
 *  - edit → save → reload → value persists;
 *  - invalid value → save blocked → inline generic error;
 *  - accessibility: label association, `aria-invalid` / `aria-describedby`.
 *
 * The `GET`/`PUT /api/settings/rules` endpoint is mocked so the spec is
 * deterministic and exercises the frontend in isolation. A server-side `store`
 * makes the round-trip test (save → reload → persists) real against the mock.
 */

/** The catalog-default `rules_config` payload the mocked GET returns. */
function defaultRulesConfig() {
  return {
    schema_version: 1,
    universe: {
      min_open_interest: 500,
      max_bid_ask_spread_pct: 10.0,
      min_iv_rank: 30.0,
      min_iv_percentile: null,
    },
    entry: {
      dte_range: { min: 21, max: 45 },
      delta_range_csp: { min: 0.2, max: 0.3 },
      delta_range_cc: { min: 0.2, max: 0.35 },
      min_monthly_return_pct: 2.0,
      earnings_buffer_days: 7,
      min_call_distance_pct: 5.0,
      min_call_distance_from_cost_basis_pct: 0.0,
    },
    position: {
      sizing_cap_pct: 25.0,
      sizing_cap_account: null,
      max_ticker_concentration_pct: 25.0,
      max_open_positions: null,
    },
    risk: {
      loss_review_threshold_pct: -15.0,
      hard_max_loss_pct: null,
      max_consecutive_rolls: null,
    },
    management: {
      profit_review_pct: 50.0,
      dte_review_days: 21,
      expiration_warning_days: 7,
      assignment_risk_review: 'High',
    },
  };
}

/**
 * Mock the rules endpoint with a persistent in-memory store so PUT then a
 * fresh GET (page reload) reflects the saved value. When `failSave` is set,
 * the PUT responds 500 so the failure path can be exercised.
 */
function mockRulesEndpoint(page, { failSave = false } = {}) {
  const store = { config: defaultRulesConfig() };
  return page.route('**/api/settings/rules', (route) => {
    const method = route.request().method();
    if (method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(store.config),
      });
    }
    if (method === 'PUT') {
      if (failSave) {
        return route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Internal Server Error' }),
        });
      }
      const body = route.request().postDataJSON();
      store.config = body;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(body),
      });
    }
    return route.continue();
  });
}

/** Open the Settings page and switch to the Trading Rules tab. */
async function openTradingRulesTab(page) {
  await page.goto('/settings');
  await page.getByTestId('settings-rules-tab').click();
  await expect(page.getByTestId('settings-rules-form')).toBeVisible();
}

test.describe('Settings → Trading Rules — page & tabs', () => {
  test('tab bar exposes General and Trading Rules tabs', async ({ page }) => {
    await mockRulesEndpoint(page);
    await page.goto('/settings');

    await expect(page.getByTestId('settings-tab-general')).toBeVisible();
    await expect(page.getByTestId('settings-rules-tab')).toBeVisible();

    await page.getByTestId('settings-rules-tab').click();
    const tab = page.getByTestId('settings-rules-tab');
    await expect(tab).toHaveAttribute('aria-selected', 'true');
  });

  test('section header states the mental model', async ({ page }) => {
    await mockRulesEndpoint(page);
    await openTradingRulesTab(page);
    await expect(
      page.getByText('Configure your system. Set once.'),
    ).toBeVisible();
  });

  test('renders all five group cards', async ({ page }) => {
    await mockRulesEndpoint(page);
    await openTradingRulesTab(page);
    for (const group of ['universe', 'entry', 'position', 'risk', 'management']) {
      await expect(page.getByTestId(`rules-group-${group}`)).toBeVisible();
    }
  });
});

test.describe('Settings → Trading Rules — deep link (issue #235)', () => {
  test('/settings?tab=rules opens the Trading Rules tab without a click', async ({
    page,
  }) => {
    await mockRulesEndpoint(page);
    await page.goto('/settings?tab=rules');

    // The Trading Rules tab is active on arrival — the recovery-page
    // "Adjust cap →" CTAs deep-link here.
    await expect(page.getByTestId('settings-rules-tab')).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await expect(page.getByTestId('settings-tab-general')).toHaveAttribute(
      'aria-selected',
      'false',
    );
    await expect(page.getByTestId('settings-rules-form')).toBeVisible();
  });

  test('/settings with no param still defaults to the General tab', async ({
    page,
  }) => {
    await mockRulesEndpoint(page);
    await page.goto('/settings');

    await expect(page.getByTestId('settings-tab-general')).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await expect(page.getByTestId('settings-rules-tab')).toHaveAttribute(
      'aria-selected',
      'false',
    );
  });

  test('an unrecognized tab param falls back to the General tab', async ({
    page,
  }) => {
    await mockRulesEndpoint(page);
    await page.goto('/settings?tab=bogus');

    await expect(page.getByTestId('settings-tab-general')).toHaveAttribute(
      'aria-selected',
      'true',
    );
  });
});

test.describe('Settings → Trading Rules — field render', () => {
  test('a field renders with its label, helper text and value', async ({
    page,
  }) => {
    await mockRulesEndpoint(page);
    await openTradingRulesTab(page);

    const input = page.getByTestId('rules-field-min_open_interest');
    await expect(input).toHaveValue('500');

    const group = page.getByTestId('rules-group-universe');
    await expect(group.getByText('Min option open interest')).toBeVisible();
    await expect(
      group.getByText(/standard liquidity floor for retail premium sellers/),
    ).toBeVisible();
  });

  test('the two cost-basis fields have distinct labels (Q6)', async ({
    page,
  }) => {
    await mockRulesEndpoint(page);
    await openTradingRulesTab(page);
    const group = page.getByTestId('rules-group-entry');
    await expect(
      group.getByText('Min call distance above cost basis (margin)'),
    ).toBeVisible();
    await expect(
      group.getByText('Min call distance — hard cost-basis floor'),
    ).toBeVisible();
  });

  test('whole-percent values render 1:1 with no fraction conversion', async ({
    page,
  }) => {
    await mockRulesEndpoint(page);
    await openTradingRulesTab(page);
    // 25% stored as the whole number 25 — not 0.25.
    await expect(
      page.getByTestId('rules-field-max_ticker_concentration_pct'),
    ).toHaveValue('25');
    // Negative whole-percent loss threshold.
    await expect(
      page.getByTestId('rules-field-loss_review_threshold_pct'),
    ).toHaveValue('-15');
  });

  test('assignment_risk_review renders as a Low/Medium/High select', async ({
    page,
  }) => {
    await mockRulesEndpoint(page);
    await openTradingRulesTab(page);
    const select = page.getByTestId('rules-field-assignment_risk_review');
    await expect(select).toHaveValue('High');
    await expect(select.locator('option')).toHaveText([
      'Low',
      'Medium',
      'High',
    ]);
  });
});

test.describe('Settings → Trading Rules — Optional fields', () => {
  test('an unset Optional field renders empty with a non-numeric placeholder', async ({
    page,
  }) => {
    await mockRulesEndpoint(page);
    await openTradingRulesTab(page);

    const input = page.getByTestId('rules-field-max_open_positions');
    await expect(input).toHaveValue('');
    await expect(input).toHaveAttribute('placeholder', 'Not set — no limit');
    // The Optional pill marks blank as a valid state.
    const group = page.getByTestId('rules-group-position');
    await expect(group.getByText('Optional', { exact: true })).toBeVisible();
  });

  test('an Optional field saves as null when left blank — not 0', async ({
    page,
  }) => {
    let savedBody = null;
    const store = { config: defaultRulesConfig() };
    await page.route('**/api/settings/rules', (route) => {
      const method = route.request().method();
      if (method === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(store.config),
        });
      }
      savedBody = route.request().postDataJSON();
      store.config = savedBody;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(savedBody),
      });
    });

    await openTradingRulesTab(page);
    // Make an unrelated edit so Save enables, leaving the Optional field blank.
    await page.getByTestId('rules-field-min_open_interest').fill('600');
    await page.getByTestId('settings-save-rules').click();
    await expect(page.getByTestId('settings-rules-save-success')).toBeVisible();

    expect(savedBody).not.toBeNull();
    expect(savedBody.position.max_open_positions).toBeNull();
    expect(savedBody.risk.hard_max_loss_pct).toBeNull();
    expect(savedBody.risk.max_consecutive_rolls).toBeNull();
    expect(savedBody.universe.min_iv_percentile).toBeNull();
  });

  test('a Clear button returns a set Optional field to unset', async ({
    page,
  }) => {
    await mockRulesEndpoint(page);
    await openTradingRulesTab(page);

    const input = page.getByTestId('rules-field-max_open_positions');
    await input.fill('8');
    await expect(
      page.getByTestId('rules-field-max_open_positions-clear'),
    ).toBeVisible();
    await page.getByTestId('rules-field-max_open_positions-clear').click();
    await expect(input).toHaveValue('');
  });
});

test.describe('Settings → Trading Rules — validation', () => {
  test('an inverted range (min >= max) shows an inline error and blocks save', async ({
    page,
  }) => {
    await mockRulesEndpoint(page);
    await openTradingRulesTab(page);

    await page.getByTestId('rules-field-dte_range_min').fill('60');
    await page.getByTestId('rules-field-dte_range_max').fill('30');
    await page.getByTestId('rules-field-dte_range_max').blur();

    const error = page.getByTestId('rules-field-dte_range-error');
    await expect(error).toBeVisible();
    await expect(error).toHaveText('Minimum must be less than maximum.');
    await expect(page.getByTestId('settings-save-rules')).toBeDisabled();
  });

  test('a delta bound outside 0–1 shows an inline error', async ({ page }) => {
    await mockRulesEndpoint(page);
    await openTradingRulesTab(page);

    await page.getByTestId('rules-field-delta_range_csp_max').fill('1.5');
    await page.getByTestId('rules-field-delta_range_csp_max').blur();

    const error = page.getByTestId('rules-field-delta_range_csp-error');
    await expect(error).toBeVisible();
    await expect(error).toHaveText('Delta must be between 0 and 1.');
  });

  test('a positive loss threshold is rejected', async ({ page }) => {
    await mockRulesEndpoint(page);
    await openTradingRulesTab(page);

    await page.getByTestId('rules-field-loss_review_threshold_pct').fill('15');
    await page.getByTestId('rules-field-loss_review_threshold_pct').blur();

    const error = page.getByTestId(
      'rules-field-loss_review_threshold_pct-error',
    );
    await expect(error).toBeVisible();
    await expect(error).toHaveText(
      'Enter a loss as a negative percentage (0 or below).',
    );
  });

  test('a percent over 100 is rejected', async ({ page }) => {
    await mockRulesEndpoint(page);
    await openTradingRulesTab(page);

    await page.getByTestId('rules-field-min_iv_rank').fill('150');
    await page.getByTestId('rules-field-min_iv_rank').blur();

    await expect(page.getByTestId('rules-field-min_iv_rank-error')).toHaveText(
      'Enter a percentage between 0 and 100.',
    );
  });

  test('a blank Optional field is always valid', async ({ page }) => {
    await mockRulesEndpoint(page);
    await openTradingRulesTab(page);

    // Set then clear an Optional field — never an error.
    await page.getByTestId('rules-field-hard_max_loss_pct').fill('-25');
    await page.getByTestId('rules-field-hard_max_loss_pct').fill('');
    await page.getByTestId('rules-field-hard_max_loss_pct').blur();
    await expect(
      page.getByTestId('rules-field-hard_max_loss_pct-error'),
    ).toHaveCount(0);
  });
});

test.describe('Settings → Trading Rules — save lifecycle', () => {
  test('edit → save → reload → value persists', async ({ page }) => {
    await mockRulesEndpoint(page);
    await openTradingRulesTab(page);

    await page.getByTestId('rules-field-dte_range_max').fill('60');
    await page.getByTestId('settings-save-rules').click();
    await expect(page.getByTestId('settings-rules-save-success')).toBeVisible();

    // Reload the page — the mock store keeps the saved value.
    await openTradingRulesTab(page);
    await expect(page.getByTestId('rules-field-dte_range_max')).toHaveValue(
      '60',
    );
  });

  test('save failure shows a generic inline error, never a raw exception', async ({
    page,
  }) => {
    await mockRulesEndpoint(page, { failSave: true });
    await openTradingRulesTab(page);

    await page.getByTestId('rules-field-dte_range_max').fill('50');
    await page.getByTestId('settings-save-rules').click();

    const banner = page.getByTestId('settings-rules-save-error');
    await expect(banner).toBeVisible();
    await expect(banner).toContainText(
      "Couldn't save your trading rules. Please try again.",
    );
    // The raw exception text from the mock 500 must not leak.
    await expect(banner).not.toContainText('Internal Server Error');
  });

  test('Save is disabled until there is an unsaved change', async ({
    page,
  }) => {
    await mockRulesEndpoint(page);
    await openTradingRulesTab(page);

    await expect(page.getByTestId('settings-save-rules')).toBeDisabled();
    await page.getByTestId('rules-field-min_open_interest').fill('600');
    await expect(page.getByTestId('settings-save-rules')).toBeEnabled();
    await expect(
      page.getByTestId('settings-rules-unsaved-hint'),
    ).toBeVisible();
  });

  test('Reset to defaults opens a confirm dialog and restores defaults', async ({
    page,
  }) => {
    await mockRulesEndpoint(page);
    await openTradingRulesTab(page);

    await page.getByTestId('rules-field-min_open_interest').fill('999');
    await page.getByTestId('settings-reset-rules').click();
    await expect(page.getByTestId('confirm-dialog')).toBeVisible();
    await page.getByTestId('confirm-dialog-confirm').click();

    await expect(
      page.getByTestId('rules-field-min_open_interest'),
    ).toHaveValue('500');
    // Optional fields reset to unset, not to a proposed number.
    await expect(
      page.getByTestId('rules-field-max_open_positions'),
    ).toHaveValue('');
  });
});

test.describe('Settings → Trading Rules — load failure', () => {
  test('a failed config GET shows a generic error block with Retry', async ({
    page,
  }) => {
    let calls = 0;
    await page.route('**/api/settings/rules', (route) => {
      calls += 1;
      if (route.request().method() === 'GET' && calls === 1) {
        return route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Internal Server Error' }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(defaultRulesConfig()),
      });
    });

    await page.goto('/settings');
    await page.getByTestId('settings-rules-tab').click();

    const errorBlock = page.getByTestId('settings-rules-load-error');
    await expect(errorBlock).toBeVisible();
    await expect(errorBlock).toContainText(
      "Couldn't load your trading rules.",
    );
    await expect(errorBlock).not.toContainText('Internal Server Error');

    // Retry succeeds — the form renders.
    await errorBlock.getByRole('button', { name: 'Retry' }).click();
    await expect(page.getByTestId('settings-rules-form')).toBeVisible();
  });
});

test.describe('Settings → Trading Rules — accessibility', () => {
  test('every input is associated with a label', async ({ page }) => {
    await mockRulesEndpoint(page);
    await openTradingRulesTab(page);

    // A labelled scalar input.
    await expect(
      page.getByLabel('Min option open interest'),
    ).toBeVisible();
    // A range field's visually-hidden per-input labels.
    await expect(page.getByLabel('DTE minimum')).toBeVisible();
    await expect(page.getByLabel('DTE maximum')).toBeVisible();
  });

  test('a valid field has aria-invalid=false and aria-describedby its help', async ({
    page,
  }) => {
    await mockRulesEndpoint(page);
    await openTradingRulesTab(page);

    const input = page.getByTestId('rules-field-min_open_interest');
    await expect(input).toHaveAttribute('aria-invalid', 'false');
    await expect(input).toHaveAttribute(
      'aria-describedby',
      'rules-field-min_open_interest-help',
    );
  });

  test('an invalid field announces via aria-invalid and aria-describedby', async ({
    page,
  }) => {
    await mockRulesEndpoint(page);
    await openTradingRulesTab(page);

    const input = page.getByTestId('rules-field-min_iv_rank');
    await input.fill('150');
    await input.blur();

    await expect(input).toHaveAttribute('aria-invalid', 'true');
    await expect(input).toHaveAttribute(
      'aria-describedby',
      'rules-field-min_iv_rank-help rules-field-min_iv_rank-error',
    );
  });
});

// ---------------------------------------------------------------------------
// Issue #234 — Trading Rules: per-position sizing cap as % of total capital.
//
// V1.0.7 swaps the sizing-cap field from an absolute dollar amount to a
// percentage that resolves against the connected Schwab account value. The
// tests below exercise the field itself, the resolved-context line (4
// variants), the multi-account selector, the manual Refresh / Retry buttons,
// and the one-time v1→v2 migration banner.
//
// Frozen test IDs (V1 contract; see plan §V1):
//   - rules-field-sizing_cap_pct
//   - rules-field-sizing_cap_pct-resolved
//   - rules-field-sizing_cap_pct-refresh
//   - rules-field-sizing_cap_pct-reconnect
//   - rules-field-sizing_cap_pct-retry
//   - rules-position-capital-account
//   - rules-migration-banner-sizing-cap
//   - rules-migration-banner-sizing-cap-dismiss
// ---------------------------------------------------------------------------

/** Build a rules-config payload that optionally carries an inline
 * `migration.sizing_cap` row (S4 in the plan — the migration flag is served
 * inline with rules so the UI doesn't need a second round-trip). */
function rulesConfigWithMigration(migration = null) {
  const config = defaultRulesConfig();
  if (migration) config.migration = { sizing_cap: migration };
  return config;
}

/**
 * Mock the `/api/settings/rules` endpoint with a persistent in-memory store
 * that exposes the saved body and supports inline migration toggling between
 * calls (the dismiss flow stamps `dismissed_at` server-side, which a second
 * GET must surface). The `lastPut` ref lets a test assert what was sent.
 */
function mockRulesEndpointWithCapture(page, { initialMigration = null } = {}) {
  const store = {
    config: rulesConfigWithMigration(initialMigration),
    lastPut: null,
  };
  page.route('**/api/settings/rules', (route) => {
    const method = route.request().method();
    if (method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(store.config),
      });
    }
    if (method === 'PUT') {
      const body = route.request().postDataJSON();
      store.lastPut = body;
      // Preserve any migration object across save round-trips so a save
      // doesn't accidentally wipe the inline flag.
      const next = { ...body };
      if (store.config.migration) next.migration = store.config.migration;
      store.config = next;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(next),
      });
    }
    return route.continue();
  });
  return store;
}

/** Mock the Schwab account-value endpoints with a small mutable state machine.
 * `currentResult` is what GET returns; `refreshResult` is what POST returns
 * (falls back to `currentResult` when unset). Calls are counted so tests can
 * assert the Refresh / Retry buttons actually fired. */
function mockAccountValueEndpoints(page, { initialResult, refreshResult } = {}) {
  const state = {
    current: initialResult || { status: 'ok', total_capital: 20000 },
    refresh: refreshResult,
    getCalls: 0,
    refreshCalls: 0,
  };
  page.route('**/api/settings/account-value', (route) => {
    state.getCalls += 1;
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(state.current),
    });
  });
  page.route('**/api/settings/account-value/refresh', (route) => {
    state.refreshCalls += 1;
    const body = state.refresh ?? state.current;
    // Once the refresh has fired, that becomes the new GET state so a
    // subsequent re-mount sees the post-refresh shape.
    state.current = body;
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });
  });
  return state;
}

/** Mock the one-time migration-dismiss endpoint. Captures the call count
 * so tests can assert the button fired (it's a side-effecting POST). */
function mockMigrationDismiss(page) {
  const state = { calls: 0 };
  page.route('**/api/settings/rules/migration/sizing-cap/dismiss', (route) => {
    state.calls += 1;
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        previous_sizing_cap_dollars: 5000,
        migrated_at: '2026-05-19T12:00:00+00:00',
        dismissed_at: '2026-05-19T12:05:00+00:00',
      }),
    });
  });
  return state;
}

test.describe('Sizing cap percent — V1.0.7 (#234)', () => {
  test('field renders with % suffix and default 25', async ({ page }) => {
    mockRulesEndpointWithCapture(page);
    mockAccountValueEndpoints(page, {
      initialResult: {
        status: 'ok',
        total_capital: 20000,
        account_id_masked: '…4471',
      },
    });
    await openTradingRulesTab(page);

    const input = page.getByTestId('rules-field-sizing_cap_pct');
    await expect(input).toBeVisible();
    await expect(input).toHaveValue('25');

    // The catalog declares a trailing `%` suffix span next to the input. It's
    // aria-hidden, so locate it by text within the Position card.
    const positionGroup = page.getByTestId('rules-group-position');
    await expect(positionGroup.locator('span', { hasText: '%' }).first()).toBeVisible();
  });

  test('field accepts decimal entry', async ({ page }) => {
    mockRulesEndpointWithCapture(page);
    mockAccountValueEndpoints(page, {
      initialResult: { status: 'ok', total_capital: 20000 },
    });
    await openTradingRulesTab(page);

    const input = page.getByTestId('rules-field-sizing_cap_pct');
    await input.fill('7.5');
    await input.blur();

    await expect(input).toHaveValue('7.5');
    await expect(
      page.getByTestId('rules-field-sizing_cap_pct-error'),
    ).toHaveCount(0);
  });

  test('field rejects out-of-range entry', async ({ page }) => {
    mockRulesEndpointWithCapture(page);
    mockAccountValueEndpoints(page, {
      initialResult: { status: 'ok', total_capital: 20000 },
    });
    await openTradingRulesTab(page);

    const input = page.getByTestId('rules-field-sizing_cap_pct');
    await input.fill('150');
    await input.blur();

    const error = page.getByTestId('rules-field-sizing_cap_pct-error');
    await expect(error).toBeVisible();
    await expect(error).toHaveText(
      'Enter a percentage greater than 0 and up to 100.',
    );
  });

  test('resolved-context line shows OK variant with masked account and dollar', async ({
    page,
  }) => {
    mockRulesEndpointWithCapture(page);
    mockAccountValueEndpoints(page, {
      initialResult: {
        status: 'ok',
        total_capital: 20000,
        account_id_masked: '…4471',
        resolved_sizing_cap_dollars: 5000,
      },
    });
    await openTradingRulesTab(page);

    const resolved = page.getByTestId('rules-field-sizing_cap_pct-resolved');
    await expect(resolved).toBeVisible();
    await expect(resolved).toHaveAttribute('data-state', 'ok');
    await expect(resolved).toContainText('25%');
    await expect(resolved).toContainText('…4471');
    await expect(resolved).toContainText('$5,000');

    await expect(
      page.getByTestId('rules-field-sizing_cap_pct-refresh'),
    ).toBeVisible();
  });

  test('resolved-context line shows DISCONNECTED variant with Reconnect button', async ({
    page,
  }) => {
    mockRulesEndpointWithCapture(page);
    mockAccountValueEndpoints(page, {
      initialResult: { status: 'disconnected' },
    });
    await openTradingRulesTab(page);

    const resolved = page.getByTestId('rules-field-sizing_cap_pct-resolved');
    await expect(resolved).toBeVisible();
    await expect(resolved).toHaveAttribute('data-state', 'disconnected');

    const reconnect = page.getByTestId('rules-field-sizing_cap_pct-reconnect');
    await expect(reconnect).toBeVisible();

    // The button fires `onSwitchToTab('general')` which flips aria-selected on
    // the tab bar (no URL change — settings nav is query-param based but the
    // tab callback updates local state, not the URL).
    await reconnect.click();
    await expect(page.getByTestId('settings-tab-general')).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await expect(page.getByTestId('settings-rules-tab')).toHaveAttribute(
      'aria-selected',
      'false',
    );
  });

  test('resolved-context line shows EXPIRED variant', async ({ page }) => {
    mockRulesEndpointWithCapture(page);
    mockAccountValueEndpoints(page, {
      initialResult: { status: 'expired' },
    });
    await openTradingRulesTab(page);

    const resolved = page.getByTestId('rules-field-sizing_cap_pct-resolved');
    await expect(resolved).toBeVisible();
    await expect(resolved).toHaveAttribute('data-state', 'expired');
    // Disconnected and expired share the Reconnect button per the design spec.
    await expect(
      page.getByTestId('rules-field-sizing_cap_pct-reconnect'),
    ).toBeVisible();
  });

  test('resolved-context line shows ERROR variant with Retry button', async ({
    page,
  }) => {
    mockRulesEndpointWithCapture(page);
    mockAccountValueEndpoints(page, {
      initialResult: { status: 'error' },
    });
    await openTradingRulesTab(page);

    const resolved = page.getByTestId('rules-field-sizing_cap_pct-resolved');
    await expect(resolved).toBeVisible();
    await expect(resolved).toHaveAttribute('data-state', 'error');
    await expect(
      page.getByTestId('rules-field-sizing_cap_pct-retry'),
    ).toBeVisible();
  });

  test('Refresh button triggers POST /account-value/refresh and updates the display', async ({
    page,
  }) => {
    mockRulesEndpointWithCapture(page);
    const acct = mockAccountValueEndpoints(page, {
      initialResult: {
        status: 'ok',
        total_capital: 20000,
        account_id_masked: '…4471',
        resolved_sizing_cap_dollars: 5000,
      },
      refreshResult: {
        status: 'ok',
        total_capital: 25000,
        account_id_masked: '…4471',
        resolved_sizing_cap_dollars: 6250,
      },
    });
    await openTradingRulesTab(page);

    // Sanity: the initial OK variant resolves to $5,000.
    const resolved = page.getByTestId('rules-field-sizing_cap_pct-resolved');
    await expect(resolved).toContainText('$5,000');

    await page.getByTestId('rules-field-sizing_cap_pct-refresh').click();

    // After the force-refresh, total_capital is 25,000 → 25% = $6,250.
    await expect(resolved).toContainText('$6,250');
    expect(acct.refreshCalls).toBe(1);
  });

  test('Retry button triggers force-refresh from error state', async ({
    page,
  }) => {
    mockRulesEndpointWithCapture(page);
    const acct = mockAccountValueEndpoints(page, {
      initialResult: { status: 'error' },
      refreshResult: {
        status: 'ok',
        total_capital: 20000,
        account_id_masked: '…4471',
        resolved_sizing_cap_dollars: 5000,
      },
    });
    await openTradingRulesTab(page);

    const resolved = page.getByTestId('rules-field-sizing_cap_pct-resolved');
    await expect(resolved).toHaveAttribute('data-state', 'error');

    await page.getByTestId('rules-field-sizing_cap_pct-retry').click();

    await expect(resolved).toHaveAttribute('data-state', 'ok');
    await expect(resolved).toContainText('$5,000');
    expect(acct.refreshCalls).toBe(1);
  });

  test('Multi-account selector visible when accounts.length > 1', async ({
    page,
  }) => {
    mockRulesEndpointWithCapture(page);
    mockAccountValueEndpoints(page, {
      initialResult: {
        status: 'ok',
        total_capital: 20000,
        account_id_masked: '…4471',
        resolved_sizing_cap_dollars: 5000,
        accounts: [
          { account_id_masked: '…4471', account_type: 'Brokerage' },
          { account_id_masked: '…8888', account_type: 'Brokerage' },
        ],
      },
    });
    await openTradingRulesTab(page);

    await expect(
      page.getByTestId('rules-position-capital-account'),
    ).toBeVisible();
  });

  test('Multi-account selector hidden in the single-account case', async ({
    page,
  }) => {
    mockRulesEndpointWithCapture(page);
    mockAccountValueEndpoints(page, {
      initialResult: {
        status: 'ok',
        total_capital: 20000,
        account_id_masked: '…4471',
        resolved_sizing_cap_dollars: 5000,
        accounts: [{ account_id_masked: '…4471', account_type: 'Brokerage' }],
      },
    });
    await openTradingRulesTab(page);

    // Wait until the form is up so the (negative) assertion isn't racing the
    // initial render.
    await expect(page.getByTestId('settings-rules-form')).toBeVisible();
    await expect(
      page.getByTestId('rules-position-capital-account'),
    ).toHaveCount(0);
  });

  test('Multi-account selector saves selection through rules-config', async ({
    page,
  }) => {
    const store = mockRulesEndpointWithCapture(page);
    mockAccountValueEndpoints(page, {
      initialResult: {
        status: 'ok',
        total_capital: 20000,
        account_id_masked: '…4471',
        resolved_sizing_cap_dollars: 5000,
        accounts: [
          { account_id_masked: '…4471', account_type: 'Brokerage' },
          { account_id_masked: '…8888', account_type: 'Brokerage' },
        ],
      },
    });
    await openTradingRulesTab(page);

    const select = page.getByTestId('rules-position-capital-account');
    await expect(select).toBeVisible();
    await select.selectOption('…8888');

    await page.getByTestId('settings-save-rules').click();
    await expect(
      page.getByTestId('settings-rules-save-success'),
    ).toBeVisible();

    // The PUT body carries the new sizing_cap_account inside position.
    expect(store.lastPut).not.toBeNull();
    expect(store.lastPut.position.sizing_cap_account).toBe('…8888');
  });

  test('Migration banner appears on first load when migration row is present', async ({
    page,
  }) => {
    mockRulesEndpointWithCapture(page, {
      initialMigration: {
        previous_sizing_cap_dollars: 5000,
        migrated_at: '2026-05-19T12:00:00+00:00',
        dismissed_at: null,
      },
    });
    mockAccountValueEndpoints(page, {
      initialResult: { status: 'ok', total_capital: 20000 },
    });
    mockMigrationDismiss(page);
    await openTradingRulesTab(page);

    const banner = page.getByTestId('rules-migration-banner-sizing-cap');
    await expect(banner).toBeVisible();
    // Copy includes the previous dollar value and the new 25% default.
    await expect(banner).toContainText('5,000');
    await expect(banner).toContainText('25%');
  });

  test('Migration banner dismisses on click and does not reappear after reload', async ({
    page,
  }) => {
    // First load: banner present (dismissed_at = null).
    const store = mockRulesEndpointWithCapture(page, {
      initialMigration: {
        previous_sizing_cap_dollars: 5000,
        migrated_at: '2026-05-19T12:00:00+00:00',
        dismissed_at: null,
      },
    });
    mockAccountValueEndpoints(page, {
      initialResult: { status: 'ok', total_capital: 20000 },
    });
    const dismissState = mockMigrationDismiss(page);
    await openTradingRulesTab(page);

    const banner = page.getByTestId('rules-migration-banner-sizing-cap');
    await expect(banner).toBeVisible();

    await page.getByTestId('rules-migration-banner-sizing-cap-dismiss').click();
    await expect(banner).toHaveCount(0);
    // Allow the optimistic POST to land.
    await expect.poll(() => dismissState.calls).toBe(1);

    // Simulate the server now returning the dismissed-at timestamp by
    // mutating the mock store. A reload re-fetches and must keep the banner
    // hidden (the pre-dismissed path).
    store.config = rulesConfigWithMigration({
      previous_sizing_cap_dollars: 5000,
      migrated_at: '2026-05-19T12:00:00+00:00',
      dismissed_at: '2026-05-19T12:05:00+00:00',
    });

    await openTradingRulesTab(page);
    await expect(
      page.getByTestId('rules-migration-banner-sizing-cap'),
    ).toHaveCount(0);
  });
});
