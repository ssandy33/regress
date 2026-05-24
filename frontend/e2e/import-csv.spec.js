import { test, expect } from '@playwright/test';

const SAMPLE_CSV = [
  'Date,Action,Symbol,Description,Quantity,Price,Fees & Comm,Amount',
  '"03/01/2026","Sell to Open","F 03/27/2026 13.50 P","PUT FORD",1,0.30,0.65,29.35',
  '"03/02/2026","Sell to Open","SOFI 03/20/2026 31.00 C","CALL SOFI",2,0.50,1.30,98.70',
].join('\n');

const MOCK_CSV_PREVIEW = {
  account_number: '',
  trades: [
    {
      ticker: 'F',
      trade_type: 'sell_put',
      strike: 13.5,
      expiration: '2026-03-27',
      premium: 0.2935,
      fees: 0.65,
      quantity: 1,
      opened_at: '2026-03-01',
      is_duplicate: false,
    },
    {
      ticker: 'SOFI',
      trade_type: 'sell_call',
      strike: 31.0,
      expiration: '2026-03-20',
      premium: 0.4935,
      fees: 1.3,
      quantity: 2,
      opened_at: '2026-03-02',
      is_duplicate: false,
    },
  ],
  total: 2,
  duplicates: 0,
  new_count: 2,
};

const MOCK_CSV_IMPORT_RESULT = {
  imported: 2,
  skipped_duplicates: 0,
  positions_created: 2,
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
    page.route('**/api/journal/import/csv/preview', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_CSV_PREVIEW),
      })
    ),
    page.route('**/api/journal/import/csv', (route) => {
      if (route.request().method() === 'POST') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(MOCK_CSV_IMPORT_RESULT),
        });
      }
      return route.continue();
    }),
  ]);
}

test.describe('Schwab CSV Import (issue #104) @e2e', () => {
  test.beforeEach(async ({ page }) => {
    await setupMocks(page);
    await page.goto('/journal');
  });

  test('mode toggle is visible and switches the input UI', async ({ page }) => {
    await page.getByTestId('import-schwab-btn').click();
    await expect(page.getByTestId('import-modal')).toBeVisible();

    // Default mode is API — date inputs visible, file input hidden.
    await expect(page.getByTestId('import-mode-toggle')).toBeVisible();
    await expect(page.getByTestId('import-api-fields')).toBeVisible();
    await expect(page.getByTestId('import-csv-fields')).toHaveCount(0);

    // Switch to CSV — file input visible, date inputs hidden.
    await page.getByTestId('import-mode-csv').click();
    await expect(page.getByTestId('import-csv-fields')).toBeVisible();
    await expect(page.getByTestId('import-api-fields')).toHaveCount(0);
    await expect(page.getByTestId('csv-file-input')).toBeVisible();

    // And back to API.
    await page.getByTestId('import-mode-api').click();
    await expect(page.getByTestId('import-api-fields')).toBeVisible();
    await expect(page.getByTestId('import-csv-fields')).toHaveCount(0);
  });

  test('preview button is disabled until a CSV file is selected', async ({ page }) => {
    await page.getByTestId('import-schwab-btn').click();
    await page.getByTestId('import-mode-csv').click();
    await expect(page.getByTestId('preview-csv-btn')).toBeDisabled();
  });

  test('selecting a CSV file then previewing renders trade rows', async ({ page }) => {
    await page.getByTestId('import-schwab-btn').click();
    await page.getByTestId('import-mode-csv').click();

    await page.getByTestId('csv-file-input').setInputFiles({
      name: 'schwab-trades.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from(SAMPLE_CSV, 'utf-8'),
    });

    await expect(page.getByTestId('csv-file-name')).toContainText('schwab-trades.csv');
    await expect(page.getByTestId('preview-csv-btn')).toBeEnabled();
    await page.getByTestId('preview-csv-btn').click();

    await expect(page.getByTestId('import-preview')).toBeVisible();
    await expect(page.getByText('F', { exact: true })).toBeVisible();
    await expect(page.getByText('SOFI', { exact: true })).toBeVisible();
  });

  test('full CSV import flow shows success state', async ({ page }) => {
    await page.getByTestId('import-schwab-btn').click();
    await page.getByTestId('import-mode-csv').click();

    await page.getByTestId('csv-file-input').setInputFiles({
      name: 'schwab-trades.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from(SAMPLE_CSV, 'utf-8'),
    });
    await page.getByTestId('preview-csv-btn').click();
    await expect(page.getByTestId('import-preview')).toBeVisible();

    await page.getByTestId('confirm-import-btn').click();
    await expect(page.getByTestId('import-result')).toBeVisible();
    await expect(page.getByText('Imported: 2 trades')).toBeVisible();
    await expect(page.getByText('Positions created: 2')).toBeVisible();
  });

  test('Position Strategy dropdown is removed in CSV mode (issue #131)', async ({ page }) => {
    await page.getByTestId('import-schwab-btn').click();
    await page.getByTestId('import-mode-csv').click();
    const modal = page.getByTestId('import-modal');
    await expect(modal.getByText('Position Strategy')).toHaveCount(0);

    await page.getByTestId('csv-file-input').setInputFiles({
      name: 'schwab-trades.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from(SAMPLE_CSV, 'utf-8'),
    });
    await page.getByTestId('preview-csv-btn').click();
    await expect(page.getByTestId('import-preview')).toBeVisible();
    // Still gone after preview (the dropdown previously appeared on this view).
    await expect(modal.getByText('Position Strategy')).toHaveCount(0);
  });

  test('CSV import POST omits position_strategy form field (issue #131)', async ({ page }) => {
    const csvBodies = [];
    await page.unroute('**/api/journal/import/csv');
    await page.route('**/api/journal/import/csv', (route) => {
      const req = route.request();
      if (req.method() === 'POST') {
        const raw = req.postData() || '';
        csvBodies.push(raw);
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(MOCK_CSV_IMPORT_RESULT),
        });
      }
      return route.continue();
    });

    await page.getByTestId('import-schwab-btn').click();
    await page.getByTestId('import-mode-csv').click();
    await page.getByTestId('csv-file-input').setInputFiles({
      name: 'schwab-trades.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from(SAMPLE_CSV, 'utf-8'),
    });
    await page.getByTestId('preview-csv-btn').click();
    await expect(page.getByTestId('import-preview')).toBeVisible();
    await page.getByTestId('confirm-import-btn').click();
    await expect(page.getByTestId('import-result')).toBeVisible();

    expect(csvBodies.length).toBe(1);
    // The multipart body should not contain a `position_strategy` part.
    expect(csvBodies[0]).not.toMatch(/name="position_strategy"/);
  });

  test('non-CSV file shows client-side validation error', async ({ page }) => {
    await page.getByTestId('import-schwab-btn').click();
    await page.getByTestId('import-mode-csv').click();

    await page.getByTestId('csv-file-input').setInputFiles({
      name: 'nope.txt',
      mimeType: 'text/plain',
      buffer: Buffer.from('hello'),
    });

    await expect(page.getByTestId('csv-error')).toContainText('.csv');
    await expect(page.getByTestId('preview-csv-btn')).toBeDisabled();
  });

  test('confirm posts to CSV endpoint, not API endpoint', async ({ page }) => {
    const csvCalls = [];
    const apiCalls = [];
    await page.unroute('**/api/journal/import/csv');
    await page.route('**/api/journal/import/csv', (route) => {
      if (route.request().method() === 'POST') {
        csvCalls.push(route.request().url());
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(MOCK_CSV_IMPORT_RESULT),
        });
      }
      return route.continue();
    });
    await page.route('**/api/journal/import', (route) => {
      if (route.request().method() === 'POST') {
        apiCalls.push(route.request().url());
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ imported: 0, skipped_duplicates: 0, positions_created: 0 }),
        });
      }
      return route.continue();
    });

    await page.getByTestId('import-schwab-btn').click();
    await page.getByTestId('import-mode-csv').click();
    await page.getByTestId('csv-file-input').setInputFiles({
      name: 'schwab-trades.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from(SAMPLE_CSV, 'utf-8'),
    });
    await page.getByTestId('preview-csv-btn').click();
    await expect(page.getByTestId('import-preview')).toBeVisible();
    await page.getByTestId('confirm-import-btn').click();
    await expect(page.getByTestId('import-result')).toBeVisible();

    expect(csvCalls.length).toBe(1);
    expect(apiCalls.length).toBe(0);
  });
});
