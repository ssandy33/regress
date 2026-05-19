import { test, expect } from '@playwright/test';

/**
 * Settings → Trading Objectives section (issue #207).
 *
 * The V1.0.3 stopgap: a new third Settings tab holding a single field —
 * Target yield — that un-dead-ends the Recovery Plan "Set target yield →"
 * CTA. Covers the issue's automated-coverage ACs:
 *  - `?tab=objectives` deep link selects the Trading Objectives tab;
 *  - the Target Yield field renders in `settings-objectives-section`, not
 *    inside a Trading Rules group card;
 *  - enter a value → save → reload → value persists (whole-percent ↔ the
 *    fraction the backend stores);
 *  - an out-of-bounds value shows the inline error and blocks Save.
 *
 * The generic `GET`/`PUT /api/settings` endpoint is mocked with a persistent
 * in-memory store so the round-trip test is real against the mock. The store
 * holds `okr_target_yield` as a FRACTION (what the backend stores); the UI
 * converts to/from whole-percent.
 */

/** A baseline SettingsResponse — the fields the page reads. */
function settingsResponse(okrTargetYield = null) {
  return {
    fred_api_key_set: false,
    cache_ttl_daily_hours: 24,
    cache_ttl_monthly_days: 30,
    default_date_range_years: 5,
    theme: 'system',
    schwab_configured: false,
    schwab_token_expires: null,
    okr_target_yield: okrTargetYield,
  };
}

/**
 * Mock the generic settings endpoint with a persistent in-memory store so a
 * PUT then a fresh GET (page reload) reflects the saved value. The store
 * keeps `okr_target_yield` as the stored fraction. When `failSave` is set the
 * PUT responds 500 so the failure path can be exercised.
 */
function mockSettingsEndpoint(page, { initial = null, failSave = false } = {}) {
  const store = { okrTargetYield: initial };
  return page.route('**/api/settings', (route) => {
    const method = route.request().method();
    if (method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(settingsResponse(store.okrTargetYield)),
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
      if (body?.key === 'okr_target_yield') {
        store.okrTargetYield = Number(body.value);
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'ok', key: body?.key }),
      });
    }
    return route.continue();
  });
}

/** Open the Settings page and switch to the Trading Objectives tab. */
async function openObjectivesTab(page) {
  await page.goto('/settings');
  await page.getByTestId('settings-objectives-tab').click();
  await expect(page.getByTestId('settings-objectives-section')).toBeVisible();
}

test.describe('Settings → Trading Objectives — tab & deep link', () => {
  test('the tab bar exposes a third "Trading Objectives" tab', async ({
    page,
  }) => {
    await mockSettingsEndpoint(page);
    await page.goto('/settings');

    const tab = page.getByTestId('settings-objectives-tab');
    await expect(tab).toBeVisible();
    await expect(tab).toHaveText('Trading Objectives');
  });

  test('/settings?tab=objectives opens the Trading Objectives tab without a click', async ({
    page,
  }) => {
    await mockSettingsEndpoint(page);
    await page.goto('/settings?tab=objectives');

    // The recovery-page "Set target yield →" CTA deep-links here (issue #207).
    await expect(page.getByTestId('settings-objectives-tab')).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await expect(page.getByTestId('settings-tab-general')).toHaveAttribute(
      'aria-selected',
      'false',
    );
    await expect(page.getByTestId('settings-objectives-section')).toBeVisible();
  });

  test('/settings with no param still defaults to the General tab', async ({
    page,
  }) => {
    await mockSettingsEndpoint(page);
    await page.goto('/settings');

    await expect(page.getByTestId('settings-tab-general')).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await expect(page.getByTestId('settings-objectives-tab')).toHaveAttribute(
      'aria-selected',
      'false',
    );
  });
});

test.describe('Settings → Trading Objectives — field render', () => {
  test('the Target Yield field renders inside settings-objectives-section, not a rules group', async ({
    page,
  }) => {
    await mockSettingsEndpoint(page);
    await openObjectivesTab(page);

    const section = page.getByTestId('settings-objectives-section');
    // The field lives inside the objectives section.
    await expect(
      section.getByTestId('settings-objectives-target-yield'),
    ).toBeVisible();
    await expect(
      section.getByText('Target yield', { exact: true }),
    ).toBeVisible();
    // It is NOT folded into a Trading Rules group card (issue #207 / ADR-001 —
    // target yield is an objective, not a rule).
    await expect(
      page.locator('[data-testid^="rules-group-"]'),
    ).toHaveCount(0);
  });

  test('an unset target yield renders blank with the unset note', async ({
    page,
  }) => {
    await mockSettingsEndpoint(page, { initial: null });
    await openObjectivesTab(page);

    const input = page.getByTestId('settings-objectives-target-yield');
    await expect(input).toHaveValue('');
    await expect(input).toHaveAttribute('placeholder', 'e.g. 12');
    // The unset note explains the Recovery Plan consequence.
    await expect(
      page.getByTestId('settings-objectives-unset-note'),
    ).toBeVisible();
    // Save is disabled while the field is blank.
    await expect(page.getByTestId('settings-objectives-save')).toBeDisabled();
  });

  test('a stored fraction renders as whole percent in the input', async ({
    page,
  }) => {
    // The mock store holds 0.12 (fraction); the field shows 12 (whole percent).
    await mockSettingsEndpoint(page, { initial: 0.12 });
    await openObjectivesTab(page);

    await expect(
      page.getByTestId('settings-objectives-target-yield'),
    ).toHaveValue('12');
    // A populated value has no unset note.
    await expect(
      page.getByTestId('settings-objectives-unset-note'),
    ).toHaveCount(0);
  });
});

test.describe('Settings → Trading Objectives — save lifecycle', () => {
  test('enter a value → save → reload → value persists', async ({ page }) => {
    await mockSettingsEndpoint(page, { initial: null });
    await openObjectivesTab(page);

    await page.getByTestId('settings-objectives-target-yield').fill('15');
    await page.getByTestId('settings-objectives-save').click();
    await expect(
      page.getByTestId('settings-objectives-save-success'),
    ).toBeVisible();

    // Reload — the mock store kept the saved fraction (0.15); the field
    // re-renders it as the whole percent 15.
    await openObjectivesTab(page);
    await expect(
      page.getByTestId('settings-objectives-target-yield'),
    ).toHaveValue('15');
    await expect(
      page.getByTestId('settings-objectives-unset-note'),
    ).toHaveCount(0);
  });

  test('a decimal whole-percent value round-trips through the fraction store', async ({
    page,
  }) => {
    await mockSettingsEndpoint(page, { initial: null });
    await openObjectivesTab(page);

    // 12.5% → stored fraction 0.125 → reloads cleanly (no float artefact).
    await page.getByTestId('settings-objectives-target-yield').fill('12.5');
    await page.getByTestId('settings-objectives-save').click();
    await expect(
      page.getByTestId('settings-objectives-save-success'),
    ).toBeVisible();

    await openObjectivesTab(page);
    await expect(
      page.getByTestId('settings-objectives-target-yield'),
    ).toHaveValue('12.5');
  });

  test('Save is disabled until there is an unsaved change', async ({
    page,
  }) => {
    await mockSettingsEndpoint(page, { initial: 0.12 });
    await openObjectivesTab(page);

    await expect(page.getByTestId('settings-objectives-save')).toBeDisabled();
    await page.getByTestId('settings-objectives-target-yield').fill('20');
    await expect(page.getByTestId('settings-objectives-save')).toBeEnabled();
  });

  test('save failure shows a generic inline error, never a raw exception', async ({
    page,
  }) => {
    await mockSettingsEndpoint(page, { initial: null, failSave: true });
    await openObjectivesTab(page);

    await page.getByTestId('settings-objectives-target-yield').fill('15');
    await page.getByTestId('settings-objectives-save').click();

    const banner = page.getByTestId('settings-objectives-save-error');
    await expect(banner).toBeVisible();
    await expect(banner).toContainText(
      "Couldn't save your target yield. Please try again.",
    );
    // CLAUDE.md — the raw 500 exception text must not leak.
    await expect(banner).not.toContainText('Internal Server Error');
  });
});

test.describe('Settings → Trading Objectives — validation', () => {
  test('an out-of-bounds value shows an inline error and blocks Save', async ({
    page,
  }) => {
    await mockSettingsEndpoint(page, { initial: null });
    await openObjectivesTab(page);

    // 150% is out of the 0 < x ≤ 100 range.
    const input = page.getByTestId('settings-objectives-target-yield');
    await input.fill('150');
    await input.blur();

    const error = page.getByTestId('settings-objectives-target-yield-error');
    await expect(error).toBeVisible();
    await expect(error).toHaveText(
      'Enter a percentage greater than 0 and up to 100.',
    );
    await expect(input).toHaveAttribute('aria-invalid', 'true');
    await expect(page.getByTestId('settings-objectives-save')).toBeDisabled();
  });

  test('a zero value is rejected — 0% target yield is out of bounds', async ({
    page,
  }) => {
    await mockSettingsEndpoint(page, { initial: null });
    await openObjectivesTab(page);

    const input = page.getByTestId('settings-objectives-target-yield');
    await input.fill('0');
    await input.blur();

    await expect(
      page.getByTestId('settings-objectives-target-yield-error'),
    ).toHaveText('Enter a percentage greater than 0 and up to 100.');
    await expect(page.getByTestId('settings-objectives-save')).toBeDisabled();
  });

  test('the inclusive upper bound (100) is valid', async ({ page }) => {
    await mockSettingsEndpoint(page, { initial: null });
    await openObjectivesTab(page);

    const input = page.getByTestId('settings-objectives-target-yield');
    await input.fill('100');
    await input.blur();

    await expect(
      page.getByTestId('settings-objectives-target-yield-error'),
    ).toHaveCount(0);
    await expect(page.getByTestId('settings-objectives-save')).toBeEnabled();
  });
});

test.describe('Settings → Trading Objectives — load failure', () => {
  test('a failed settings GET shows a generic error block with Retry', async ({
    page,
  }) => {
    let calls = 0;
    await page.route('**/api/settings', (route) => {
      if (route.request().method() !== 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ status: 'ok' }),
        });
      }
      calls += 1;
      if (calls === 1) {
        return route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Internal Server Error' }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(settingsResponse(null)),
      });
    });

    await page.goto('/settings?tab=objectives');

    const errorBlock = page.getByTestId('settings-objectives-load-error');
    await expect(errorBlock).toBeVisible();
    await expect(errorBlock).toContainText(
      "Couldn't load your target yield.",
    );
    await expect(errorBlock).not.toContainText('Internal Server Error');

    // Retry succeeds — the section renders.
    await errorBlock.getByRole('button', { name: 'Retry' }).click();
    await expect(page.getByTestId('settings-objectives-section')).toBeVisible();
  });
});
