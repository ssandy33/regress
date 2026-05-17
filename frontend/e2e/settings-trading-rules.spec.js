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
      sizing_cap_dollars: 5000.0,
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
