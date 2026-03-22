import { test, expect } from '@playwright/test';

const MOCK_PREVIEW = {
  account_number: '****5678',
  trades: [
    {
      ticker: 'AAPL',
      trade_type: 'sell_put',
      strike: 150.0,
      expiration: '2025-03-21',
      premium: 3.0,
      fees: 0.65,
      quantity: 1,
      opened_at: '2025-03-01T10:00:00Z',
      is_duplicate: false,
    },
    {
      ticker: 'MSFT',
      trade_type: 'sell_call',
      strike: 400.0,
      expiration: '2025-04-18',
      premium: 5.0,
      fees: 0.0,
      quantity: 1,
      opened_at: '2025-03-02T10:00:00Z',
      is_duplicate: true,
    },
  ],
  total: 2,
  duplicates: 1,
  new_count: 1,
};

const MOCK_IMPORT_RESULT = {
  imported: 1,
  skipped_duplicates: 1,
  positions_created: 1,
};

function setupMocks(page) {
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
    page.route('**/api/journal/import/preview*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_PREVIEW),
      })
    ),
    page.route('**/api/journal/import', (route) => {
      if (route.request().method() === 'POST') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(MOCK_IMPORT_RESULT),
        });
      }
      return route.continue();
    }),
  ]);
}

test.describe('Schwab Import', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await page.goto('/journal');
  });

  test('opens and closes import modal', async ({ page }) => {
    await page.getByTestId('import-schwab-btn').click();
    await expect(page.getByTestId('import-modal')).toBeVisible();

    // Close via Cancel
    await page.getByRole('button', { name: 'Cancel' }).click();
    await expect(page.getByTestId('import-modal')).not.toBeVisible();
  });

  test('preview shows trade rows', async ({ page }) => {
    await page.getByTestId('import-schwab-btn').click();
    await page.getByTestId('preview-import-btn').click();

    await expect(page.getByTestId('import-preview')).toBeVisible();
    // Should show 2 trade rows
    await expect(page.getByText('AAPL')).toBeVisible();
    await expect(page.getByText('MSFT')).toBeVisible();
  });

  test('duplicate badge is visible', async ({ page }) => {
    await page.getByTestId('import-schwab-btn').click();
    await page.getByTestId('preview-import-btn').click();

    const badges = page.getByTestId('duplicate-badge');
    await expect(badges).toHaveCount(1);
    await expect(badges.first()).toHaveText('Duplicate');
  });

  test('full import flow with success message', async ({ page }) => {
    await page.getByTestId('import-schwab-btn').click();
    await page.getByTestId('preview-import-btn').click();
    await page.getByTestId('confirm-import-btn').click();

    await expect(page.getByTestId('import-result')).toBeVisible();
    await expect(page.getByText('Imported: 1 trades')).toBeVisible();
    await expect(page.getByText('Skipped duplicates: 1')).toBeVisible();
  });

  test('shows specific error toast when Schwab token expired', async ({ page }) => {
    await page.route('**/api/journal/import/preview*', (route) =>
      route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Schwab token has expired. Please re-authorize in Settings.' }),
      })
    );

    await page.getByTestId('import-schwab-btn').click();
    await page.getByTestId('preview-import-btn').click();

    await expect(page.getByText('Schwab token has expired. Please re-authorize in Settings.')).toBeVisible();
  });

  test('import button disabled when all duplicates', async ({ page }) => {
    const allDupPreview = {
      ...MOCK_PREVIEW,
      trades: MOCK_PREVIEW.trades.map((t) => ({ ...t, is_duplicate: true })),
      duplicates: 2,
      new_count: 0,
    };

    await page.route('**/api/journal/import/preview*', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(allDupPreview),
      })
    );

    await page.getByTestId('import-schwab-btn').click();
    await page.getByTestId('preview-import-btn').click();
    await expect(page.getByTestId('confirm-import-btn')).toBeDisabled();
  });

  test('ESC key dismisses the modal', async ({ page }) => {
    await page.getByTestId('import-schwab-btn').click();
    await expect(page.getByTestId('import-modal')).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(page.getByTestId('import-modal')).not.toBeVisible();
  });

  test('backdrop click dismisses the modal', async ({ page }) => {
    await page.getByTestId('import-schwab-btn').click();
    await expect(page.getByTestId('import-modal')).toBeVisible();

    await page.getByTestId('import-backdrop').click({ position: { x: 5, y: 5 } });
    await expect(page.getByTestId('import-modal')).not.toBeVisible();
  });

  test('clicking inside modal does not dismiss it', async ({ page }) => {
    await page.getByTestId('import-schwab-btn').click();
    await expect(page.getByTestId('import-modal')).toBeVisible();

    await page.getByTestId('import-modal').click();
    await expect(page.getByTestId('import-modal')).toBeVisible();
  });
});
