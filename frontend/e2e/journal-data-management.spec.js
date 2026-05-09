import { test, expect } from '@playwright/test';

const POSITIONS_INITIAL = [
  {
    id: 'pos-aapl',
    ticker: 'AAPL',
    shares: 100,
    broker_cost_basis: 15000.0,
    status: 'open',
    strategy: 'wheel',
    opened_at: '2025-01-15T10:00:00Z',
    closed_at: null,
    notes: null,
    total_premiums: 200.0,
    adjusted_cost_basis: 14800.0,
    min_compliant_cc_strike: 162.8,
    trades: [
      {
        id: 'trade-aapl-1',
        position_id: 'pos-aapl',
        trade_type: 'sell_put',
        strike: 145.0,
        expiration: '2025-02-21',
        premium: 2.0,
        fees: 0.65,
        quantity: 1,
        opened_at: '2025-01-15T10:00:00Z',
        closed_at: null,
        close_reason: null,
      },
    ],
  },
  {
    id: 'pos-msft',
    ticker: 'MSFT',
    shares: 100,
    broker_cost_basis: 30000.0,
    status: 'open',
    strategy: 'csp',
    opened_at: '2025-01-20T10:00:00Z',
    closed_at: null,
    notes: null,
    total_premiums: 0,
    adjusted_cost_basis: 30000.0,
    min_compliant_cc_strike: 330.0,
    trades: [],
  },
];

/**
 * Stateful mock journal store. Each test gets a fresh copy via
 * structuredClone so deletes in one test don't leak into the next.
 */
function setupMocks(page) {
  const state = { positions: structuredClone(POSITIONS_INITIAL) };

  return Promise.all([
    // Collection: GET (list) only — POST is exercised in journal.spec.js.
    page.route('**/api/journal/positions', (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ positions: state.positions }),
        });
      }
      return route.continue();
    }),

    // /api/journal/all — DELETE wipes the store and returns counts. Declared
    // before the parameterised /positions/{id} route so the literal path
    // wins matching.
    page.route('**/api/journal/all', (route) => {
      if (route.request().method() === 'DELETE') {
        const trades = state.positions.reduce(
          (acc, p) => acc + (p.trades?.length ?? 0),
          0,
        );
        const positions = state.positions.length;
        state.positions = [];
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            deleted_positions: positions,
            deleted_trades: trades,
          }),
        });
      }
      return route.continue();
    }),

    // Item: GET (detail) and DELETE (cascade).
    page.route('**/api/journal/positions/*', (route) => {
      const url = new URL(route.request().url());
      const id = url.pathname.split('/').pop();
      const method = route.request().method();
      if (method === 'GET') {
        const found = state.positions.find((p) => p.id === id);
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
      }
      if (method === 'DELETE') {
        state.positions = state.positions.filter((p) => p.id !== id);
        return route.fulfill({ status: 204 });
      }
      return route.continue();
    }),

    page.route('**/api/journal/trades/*', (route) => {
      if (route.request().method() === 'DELETE') {
        const url = new URL(route.request().url());
        const id = url.pathname.split('/').pop();
        for (const p of state.positions) {
          p.trades = (p.trades || []).filter((t) => t.id !== id);
        }
        return route.fulfill({ status: 204 });
      }
      return route.continue();
    }),
  ]);
}

test.describe('Journal data management', () => {
  test('kebab menu opens and exposes a Delete action', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/journal');
    await page.waitForLoadState('networkidle');

    const firstActionsBtn = page.getByTestId('position-actions-btn').first();
    await firstActionsBtn.click();

    const deleteBtn = page.getByTestId('position-delete-btn').first();
    await expect(deleteBtn).toBeVisible();
  });

  test('canceling the position-delete dialog keeps the row', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/journal');
    await page.waitForLoadState('networkidle');

    await expect(page.getByTestId('position-row')).toHaveCount(2);

    await page.getByTestId('position-actions-btn').first().click();
    await page.getByTestId('position-delete-btn').first().click();

    const dialog = page.getByTestId('confirm-dialog');
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: 'Cancel' }).click();

    await expect(dialog).toBeHidden();
    await expect(page.getByTestId('position-row')).toHaveCount(2);
  });

  test('confirming position delete removes the row and cascades trades', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/journal');
    await page.waitForLoadState('networkidle');

    // The first row is AAPL — open the kebab and confirm delete.
    await page.getByTestId('position-actions-btn').first().click();
    await page.getByTestId('position-delete-btn').first().click();

    const dialog = page.getByTestId('confirm-dialog');
    await expect(dialog).toContainText('AAPL');
    await expect(dialog).toContainText('1 trades');

    const [deleteRequest] = await Promise.all([
      page.waitForRequest((req) =>
        req.url().includes('/api/journal/positions/pos-aapl') && req.method() === 'DELETE'
      ),
      page.getByTestId('confirm-dialog-confirm').click(),
    ]);
    expect(deleteRequest.method()).toBe('DELETE');

    // Row is gone — only MSFT remains.
    await expect(page.getByTestId('position-row')).toHaveCount(1);
    await expect(page.getByTestId('positions-table')).not.toContainText('AAPL');
    await expect(page.getByTestId('positions-table')).toContainText('MSFT');
  });

  test('trade delete shows a confirmation and parent position remains', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/journal');
    await page.waitForLoadState('networkidle');

    // Open AAPL — it has the seeded trade.
    await page.getByTestId('position-row').first().click();
    await expect(page.getByTestId('trade-history')).toBeVisible();

    await page.getByTestId('trade-delete-btn').first().click();
    const dialog = page.getByTestId('confirm-dialog');
    await expect(dialog).toContainText('Delete trade');

    const [deleteRequest] = await Promise.all([
      page.waitForRequest((req) =>
        req.url().includes('/api/journal/trades/trade-aapl-1') && req.method() === 'DELETE'
      ),
      page.getByTestId('confirm-dialog-confirm').click(),
    ]);
    expect(deleteRequest.method()).toBe('DELETE');

    // Position row still present after trade delete.
    await expect(page.getByTestId('positions-table')).toContainText('AAPL');
  });
});

/**
 * Stub the minimum set of endpoints SettingsPage hits on mount so the
 * Danger Zone tests don't see a flood of console errors before the user
 * even reaches the disclosure. SettingsPage now also instantiates
 * `useJournal`, which fires `GET /api/journal/positions` on mount, so we
 * fulfil that with an empty list as well.
 */
function setupSettingsMocks(page) {
  return Promise.all([
    page.route('**/api/journal/positions', (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ positions: [] }),
        });
      }
      return route.continue();
    }),
    page.route('**/api/journal/all', (route) => {
      if (route.request().method() === 'DELETE') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ deleted_positions: 8, deleted_trades: 47 }),
        });
      }
      return route.continue();
    }),
  ]);
}

test.describe('Settings → Danger Zone', () => {
  test('clear-all confirm button is gated by exact "DELETE" text', async ({ page }) => {
    await setupSettingsMocks(page);

    await page.goto('/settings');
    await page.waitForLoadState('networkidle');

    const danger = page.getByTestId('danger-zone');
    await expect(danger).toBeVisible();

    // Collapsed by default — toggle to expand.
    await page.getByTestId('danger-zone-toggle').click();

    const clearBtn = page.getByTestId('clear-journal-btn');
    await expect(clearBtn).toBeDisabled();

    // Lowercase doesn't enable — exact uppercase match required.
    const input = page.getByTestId('danger-zone-confirm-input');
    await input.fill('delete');
    await expect(clearBtn).toBeDisabled();

    await input.fill('DELETE');
    await expect(clearBtn).toBeEnabled();

    const [request] = await Promise.all([
      page.waitForRequest((req) =>
        req.url().includes('/api/journal/all') && req.method() === 'DELETE'
      ),
      clearBtn.click(),
    ]);
    expect(request.method()).toBe('DELETE');
  });

  test('reset-on-collapse: re-opening the disclosure clears the typed token', async ({ page }) => {
    await setupSettingsMocks(page);

    await page.goto('/settings');
    await page.waitForLoadState('networkidle');

    const toggle = page.getByTestId('danger-zone-toggle');
    await toggle.click();

    const input = page.getByTestId('danger-zone-confirm-input');
    const clearBtn = page.getByTestId('clear-journal-btn');

    await input.fill('DELETE');
    await expect(clearBtn).toBeEnabled();

    // Collapse — input unmounts. Re-open — fresh state, button disabled.
    await toggle.click();
    await expect(input).toBeHidden();

    await toggle.click();
    await expect(input).toBeVisible();
    await expect(input).toHaveValue('');
    await expect(clearBtn).toBeDisabled();
  });

  test('trailing whitespace keeps the confirm button disabled', async ({ page }) => {
    await setupSettingsMocks(page);

    await page.goto('/settings');
    await page.waitForLoadState('networkidle');

    await page.getByTestId('danger-zone-toggle').click();

    const input = page.getByTestId('danger-zone-confirm-input');
    const clearBtn = page.getByTestId('clear-journal-btn');

    // "DELETE " with a trailing space must not satisfy the exact-match gate.
    await input.fill('DELETE ');
    await expect(clearBtn).toBeDisabled();

    // Sanity check: the same input without the trailing space arms it.
    await input.fill('DELETE');
    await expect(clearBtn).toBeEnabled();
  });
});
