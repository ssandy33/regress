import { test, expect } from '@playwright/test';

/**
 * Settings → Watchlist tab (issue #323, PRD #213 UC1–UC4).
 *
 * The minimal approved-universe gate: a 4th Settings tab holding an add input,
 * the current ticker list with per-row Remove, and an empty state. Covers the
 * issue's automated-coverage ACs:
 *  - the list reflects the persisted backend state on load (UC3);
 *  - add a ticker → it appears (UC1);
 *  - remove a ticker → it disappears (UC2);
 *  - the empty state renders the explanatory message, not a blank panel;
 *  - lowercase input is normalized (round-trips through #321's API uppercasing);
 *  - duplicate add is an idempotent no-op with an inline info note (not error);
 *  - invalid input is blocked client-side;
 *  - an initial-load failure shows the amber banner + Retry;
 *  - an add failure shows a generic inline error, never the raw server detail.
 *
 * The three `/api/watchlist` endpoints (#321) are mocked with a persistent
 * in-memory store so add → reload / remove → reload round-trips are real
 * against the mock. The store uppercase-normalizes on add (mirroring the
 * backend), so a lowercase POST surfaces as an uppercase row — exactly the
 * normalization the AC asserts. Every endpoint returns the full `{ tickers }`.
 */

/**
 * Mock the `/api/watchlist` endpoints (GET list, POST add, DELETE remove) with
 * a persistent in-memory store. The store uppercases on add and is idempotent
 * (a duplicate add / missing remove is a 200 no-op with the unchanged list),
 * mirroring #321. `failGet` / `failAdd` exercise the error paths.
 */
function mockWatchlistEndpoints(
  page,
  { initial = [], failGet = false, failAdd = false } = {},
) {
  const store = { tickers: [...initial] };
  const body = () => JSON.stringify({ tickers: store.tickers });

  return page.route('**/api/watchlist**', (route) => {
    const method = route.request().method();

    if (method === 'GET') {
      if (failGet) {
        return route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Internal Server Error' }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: body(),
      });
    }

    if (method === 'POST') {
      if (failAdd) {
        return route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Internal Server Error' }),
        });
      }
      const payload = route.request().postDataJSON();
      const symbol = String(payload?.ticker || '').trim().toUpperCase();
      if (symbol && !store.tickers.includes(symbol)) {
        store.tickers.push(symbol);
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: body(),
      });
    }

    if (method === 'DELETE') {
      const symbol = decodeURIComponent(
        route.request().url().split('/api/watchlist/')[1] || '',
      ).toUpperCase();
      store.tickers = store.tickers.filter((t) => t !== symbol);
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: body(),
      });
    }

    return route.continue();
  });
}

/** Open the Settings page and switch to the Watchlist tab. */
async function openWatchlistTab(page) {
  await page.goto('/settings');
  await page.getByTestId('settings-watchlist-tab').click();
  await expect(page.getByTestId('settings-watchlist-section')).toBeVisible();
}

test.describe('Settings → Watchlist — tab & deep link @e2e', () => {
  test('the tab bar exposes a 4th "Watchlist" tab', async ({ page }) => {
    await mockWatchlistEndpoints(page, { initial: ['AAPL'] });
    await page.goto('/settings');

    const tab = page.getByTestId('settings-watchlist-tab');
    await expect(tab).toBeVisible();
    await expect(tab).toHaveText('Watchlist');
  });

  test('/settings?tab=watchlist opens the Watchlist tab without a click', async ({
    page,
  }) => {
    await mockWatchlistEndpoints(page, { initial: ['AAPL'] });
    await page.goto('/settings?tab=watchlist');

    await expect(page.getByTestId('settings-watchlist-tab')).toHaveAttribute(
      'aria-selected',
      'true',
    );
    await expect(page.getByTestId('settings-tab-general')).toHaveAttribute(
      'aria-selected',
      'false',
    );
    await expect(page.getByTestId('settings-watchlist-section')).toBeVisible();
  });
});

test.describe('Settings → Watchlist — view persisted universe @smoke @e2e', () => {
  test('the list reflects the persisted backend state on load', async ({
    page,
  }) => {
    await mockWatchlistEndpoints(page, { initial: ['AAPL', 'MSFT', 'NVDA'] });
    await openWatchlistTab(page);

    const list = page.getByTestId('settings-watchlist-list');
    await expect(list).toBeVisible();
    await expect(page.getByTestId('settings-watchlist-item')).toHaveCount(3);
    await expect(list.getByText('AAPL', { exact: true })).toBeVisible();
    await expect(list.getByText('MSFT', { exact: true })).toBeVisible();
    await expect(list.getByText('NVDA', { exact: true })).toBeVisible();

    // The count pill shows the universe size at a glance (UC4).
    await expect(page.getByTestId('settings-watchlist-count')).toHaveText(
      '3 tickers',
    );
  });
});

test.describe('Settings → Watchlist — add a ticker @smoke @e2e', () => {
  test('add a ticker → it appears in the list', async ({ page }) => {
    await mockWatchlistEndpoints(page, { initial: ['AAPL'] });
    await openWatchlistTab(page);

    await page.getByTestId('settings-watchlist-add-input').fill('MSFT');
    await page.getByTestId('settings-watchlist-add-button').click();

    // The newly added row appears (backend-ordered; we use the returned list).
    const newRow = page.locator('[data-testid="settings-watchlist-item"][data-ticker="MSFT"]');
    await expect(newRow).toBeVisible();
    await expect(page.getByTestId('settings-watchlist-item')).toHaveCount(2);
    await expect(page.getByTestId('settings-watchlist-count')).toHaveText(
      '2 tickers',
    );
    // Input clears for fast multi-add.
    await expect(page.getByTestId('settings-watchlist-add-input')).toHaveValue('');
  });

  test('Enter in the input submits the add', async ({ page }) => {
    await mockWatchlistEndpoints(page, { initial: [] });
    await openWatchlistTab(page);

    const input = page.getByTestId('settings-watchlist-add-input');
    await input.fill('SOFI');
    await input.press('Enter');

    await expect(
      page.locator('[data-testid="settings-watchlist-item"][data-ticker="SOFI"]'),
    ).toBeVisible();
  });
});

test.describe('Settings → Watchlist — remove a ticker @e2e', () => {
  test('remove a ticker → it disappears', async ({ page }) => {
    await mockWatchlistEndpoints(page, { initial: ['AAPL', 'MSFT'] });
    await openWatchlistTab(page);

    const msftRow = page.locator(
      '[data-testid="settings-watchlist-item"][data-ticker="MSFT"]',
    );
    await msftRow.getByTestId('settings-watchlist-remove').click();

    await expect(msftRow).toHaveCount(0);
    await expect(page.getByTestId('settings-watchlist-item')).toHaveCount(1);
    await expect(page.getByTestId('settings-watchlist-count')).toHaveText(
      '1 ticker',
    );
  });

  test('removing the last ticker transitions to the empty state', async ({
    page,
  }) => {
    await mockWatchlistEndpoints(page, { initial: ['AAPL'] });
    await openWatchlistTab(page);

    await page.getByTestId('settings-watchlist-remove').click();

    await expect(page.getByTestId('settings-watchlist-list')).toHaveCount(0);
    await expect(page.getByTestId('settings-watchlist-empty')).toBeVisible();
  });
});

test.describe('Settings → Watchlist — empty state @e2e', () => {
  test('the empty state renders the explanatory message, not a blank panel', async ({
    page,
  }) => {
    await mockWatchlistEndpoints(page, { initial: [] });
    await openWatchlistTab(page);

    const empty = page.getByTestId('settings-watchlist-empty');
    await expect(empty).toBeVisible();
    await expect(empty).toContainText('Your watchlist is empty');
    await expect(empty).toContainText(
      "The Options scanner won't surface any candidates until you add names",
    );
    // No count pill / no list in the empty state.
    await expect(page.getByTestId('settings-watchlist-count')).toHaveCount(0);
    await expect(page.getByTestId('settings-watchlist-list')).toHaveCount(0);
  });
});

test.describe('Settings → Watchlist — lowercase normalization @e2e', () => {
  test('a lowercase add normalizes to uppercase in the list', async ({
    page,
  }) => {
    await mockWatchlistEndpoints(page, { initial: [] });
    await openWatchlistTab(page);

    // The trader types lowercase; #321 uppercases server-side; the row shows
    // the normalized symbol (the AC).
    await page.getByTestId('settings-watchlist-add-input').fill('amd');
    await page.getByTestId('settings-watchlist-add-button').click();

    await expect(
      page.locator('[data-testid="settings-watchlist-item"][data-ticker="AMD"]'),
    ).toBeVisible();
    await expect(
      page.getByTestId('settings-watchlist-list').getByText('AMD', { exact: true }),
    ).toBeVisible();
  });
});

test.describe('Settings → Watchlist — duplicate add @e2e', () => {
  test('adding an existing ticker shows an inline info note, not an error', async ({
    page,
  }) => {
    await mockWatchlistEndpoints(page, { initial: ['AAPL'] });
    await openWatchlistTab(page);

    await page.getByTestId('settings-watchlist-add-input').fill('aapl');
    await page.getByTestId('settings-watchlist-add-button').click();

    // Idempotent no-op: the count does not grow, an info note explains why.
    await expect(page.getByTestId('settings-watchlist-item')).toHaveCount(1);
    const note = page.getByTestId('settings-watchlist-duplicate-note');
    await expect(note).toBeVisible();
    await expect(note).toContainText('AAPL is already on your watchlist');
    // It is NOT an error.
    await expect(page.getByTestId('settings-watchlist-add-error')).toHaveCount(0);
  });
});

test.describe('Settings → Watchlist — client validation @e2e', () => {
  test('invalid input is blocked client-side with an inline validation error', async ({
    page,
  }) => {
    let postCalls = 0;
    await mockWatchlistEndpoints(page, { initial: [] });
    page.on('request', (req) => {
      if (req.url().includes('/api/watchlist') && req.method() === 'POST') {
        postCalls += 1;
      }
    });
    await openWatchlistTab(page);

    // Digits-only is rejected without firing a POST (spec §7.1).
    await page.getByTestId('settings-watchlist-add-input').fill('123');
    await page.getByTestId('settings-watchlist-add-button').click();

    const error = page.getByTestId('settings-watchlist-validation-error');
    await expect(error).toBeVisible();
    await expect(error).toHaveText('Enter a valid ticker symbol.');
    expect(postCalls).toBe(0);
  });
});

test.describe('Settings → Watchlist — load failure @e2e', () => {
  test('a failed initial GET shows the amber banner + Retry recovers', async ({
    page,
  }) => {
    let getCalls = 0;
    await page.route('**/api/watchlist**', (route) => {
      if (route.request().method() !== 'GET') return route.continue();
      getCalls += 1;
      if (getCalls === 1) {
        return route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Internal Server Error' }),
        });
      }
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ tickers: ['AAPL'] }),
      });
    });

    await page.goto('/settings?tab=watchlist');

    const banner = page.getByTestId('settings-watchlist-load-error');
    await expect(banner).toBeVisible();
    await expect(banner).toContainText("Couldn't load your watchlist.");
    await expect(banner).not.toContainText('Internal Server Error');
    // Add controls are disabled while the list is unknown.
    await expect(page.getByTestId('settings-watchlist-add-input')).toBeDisabled();

    // Retry succeeds — the list renders.
    await page.getByTestId('settings-watchlist-retry').click();
    await expect(
      page.locator('[data-testid="settings-watchlist-item"][data-ticker="AAPL"]'),
    ).toBeVisible();
  });
});

test.describe('Settings → Watchlist — add failure @e2e', () => {
  test('an add failure shows a generic inline error, never raw server detail', async ({
    page,
  }) => {
    await mockWatchlistEndpoints(page, { initial: ['AAPL'], failAdd: true });
    await openWatchlistTab(page);

    await page.getByTestId('settings-watchlist-add-input').fill('TSLA');
    await page.getByTestId('settings-watchlist-add-button').click();

    const error = page.getByTestId('settings-watchlist-add-error');
    await expect(error).toBeVisible();
    await expect(error).toContainText("Couldn't add TSLA. Try again.");
    // CLAUDE.md — the raw 500 detail must not leak.
    await expect(error).not.toContainText('Internal Server Error');
    // The trader's typing is preserved.
    await expect(page.getByTestId('settings-watchlist-add-input')).toHaveValue(
      'TSLA',
    );
  });
});
