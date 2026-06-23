import { test, expect } from '@playwright/test';

// --- Preview mocks (ImportModal) — issue #389 ---------------------------------

// Mixed CSV: 2 options + buy_stock + sell_stock + dividend = 5 rows.
const MIXED_PREVIEW = {
  account_number: '',
  trades: [
    {
      ticker: 'F',
      trade_type: 'sell_put',
      strike: 13.5,
      expiration: '2026-03-27',
      premium: 0.2935,
      unit_amount: 0,
      fees: 0.65,
      quantity: 1,
      opened_at: '2026-03-01',
      close_reason: null,
      is_duplicate: false,
    },
    {
      ticker: 'SOFI',
      trade_type: 'sell_call',
      strike: 31.0,
      expiration: '2026-03-20',
      premium: 0.4935,
      unit_amount: 0,
      fees: 1.3,
      quantity: 2,
      opened_at: '2026-03-02',
      close_reason: null,
      is_duplicate: false,
    },
    {
      ticker: 'F',
      trade_type: 'buy_stock',
      strike: null,
      expiration: null,
      premium: 0.0,
      unit_amount: 28.4,
      fees: 0.0,
      quantity: 100,
      opened_at: '2026-03-03',
      close_reason: null,
      is_duplicate: false,
    },
    {
      ticker: 'F',
      trade_type: 'sell_stock',
      strike: null,
      expiration: null,
      premium: 0.0,
      unit_amount: 31.1,
      fees: 0.0,
      quantity: 100,
      opened_at: '2026-03-04',
      close_reason: null,
      is_duplicate: false,
    },
    {
      ticker: 'F',
      trade_type: 'dividend',
      strike: null,
      expiration: null,
      premium: 0.0,
      unit_amount: 42.0,
      fees: null,
      quantity: 0,
      opened_at: '2026-03-05',
      close_reason: 'Qualified Div',
      is_duplicate: false,
    },
  ],
  total: 5,
  duplicates: 0,
  new_count: 5,
};

const OPTIONS_ONLY_PREVIEW = {
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

const SAMPLE_CSV = 'Date,Action,Symbol,Description,Quantity,Price,Fees & Comm,Amount\n';

function setupPreviewMocks(page, previewBody) {
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
        body: JSON.stringify(previewBody),
      })
    ),
  ]);
}

async function openCsvPreview(page) {
  await page.getByTestId('import-schwab-btn').click();
  await page.getByTestId('import-mode-csv').click();
  await page.getByTestId('csv-file-input').setInputFiles({
    name: 'schwab-trades.csv',
    mimeType: 'text/csv',
    buffer: Buffer.from(SAMPLE_CSV, 'utf-8'),
  });
  await page.getByTestId('preview-csv-btn').click();
  await expect(page.getByTestId('import-preview')).toBeVisible();
}

test.describe('Equity preview rendering (issue #389) @smoke @e2e', () => {
  test('mixed CSV preview: count includes equity, badges + N/A + unit_amount render', async ({
    page,
  }) => {
    await setupPreviewMocks(page, MIXED_PREVIEW);
    await page.goto('/journal');
    await openCsvPreview(page);

    // AC1f — count line reflects ALL rows (2 options + 3 equity = 5).
    const previewPanel = page.getByTestId('import-preview');
    await expect(previewPanel).toContainText('5 trades found');
    await expect(previewPanel).toContainText('5 new');

    // Three equity rows present.
    const equityRows = page.getByTestId('equity-row');
    await expect(equityRows).toHaveCount(3);

    // Each equity row shows N/A placeholders in strike + expiration cells.
    // 3 equity rows × 2 N/A (strike, exp) + dividend qty N/A = 7 placeholders.
    await expect(page.getByTestId('na-placeholder')).toHaveCount(7);

    // Row-type badges name each equity kind (AC5a).
    const badges = page.getByTestId('row-type-badge');
    await expect(badges).toHaveCount(3);
    await expect(previewPanel).toContainText('Stock Buy');
    await expect(previewPanel).toContainText('Stock Sell');
    await expect(previewPanel).toContainText('Dividend');

    // Premium cell: /sh affix for buy/sell, total (no affix) for dividend.
    await expect(previewPanel).toContainText('$28.40');
    await expect(previewPanel).toContainText('$31.10');
    await expect(previewPanel).toContainText('$42.00');
    // Two "/sh" affixes (buy + sell), never on dividend.
    await expect(previewPanel.getByText('/sh', { exact: true })).toHaveCount(2);

    // Options rows still show real labels (improved from snake_case) and no badge.
    await expect(previewPanel).toContainText('Sell Put');
    await expect(previewPanel).toContainText('Sell Call');
  });

  test('na-placeholder carries accessible "Not applicable" label (AC5d)', async ({ page }) => {
    await setupPreviewMocks(page, MIXED_PREVIEW);
    await page.goto('/journal');
    await openCsvPreview(page);

    const firstNa = page.getByTestId('na-placeholder').first();
    await expect(firstNa).toContainText('Not applicable');
  });

  test('options-only preview renders unchanged — no badges, no N/A (AC5b)', async ({ page }) => {
    await setupPreviewMocks(page, OPTIONS_ONLY_PREVIEW);
    await page.goto('/journal');
    await openCsvPreview(page);

    const previewPanel = page.getByTestId('import-preview');
    await expect(previewPanel).toContainText('2 trades found');
    await expect(page.getByTestId('equity-row')).toHaveCount(0);
    await expect(page.getByTestId('na-placeholder')).toHaveCount(0);
    await expect(page.getByTestId('row-type-badge')).toHaveCount(0);

    // Options rows show real strike + premium, no /sh affix.
    await expect(previewPanel).toContainText('$13.5');
    await expect(previewPanel).toContainText('$0.29');
    await expect(previewPanel.getByText('/sh', { exact: true })).toHaveCount(0);
  });
});

// --- Journal trade-table mocks (TradeHistory) — issues #389 + #387 ------------

const MOCK_EQUITY_POSITION = {
  id: 'pos-1',
  ticker: 'F',
  shares: 100,
  broker_cost_basis: 2840.0,
  status: 'open',
  strategy: 'wheel',
  opened_at: '2026-03-01T10:00:00Z',
  closed_at: null,
  notes: null,
  total_premiums: 0.0,
  adjusted_cost_basis: 2840.0,
  broker_cost_basis_per_share: 28.4,
  adjusted_cost_basis_per_share: 28.4,
  min_compliant_cc_strike: 31.24,
  trades: [
    {
      id: 'trade-1',
      position_id: 'pos-1',
      trade_type: 'sell_put',
      strike: 13.5,
      expiration: '2026-03-27',
      premium: 0.2935,
      unit_amount: 0,
      fees: 0.65,
      quantity: 1,
      opened_at: '2026-03-01T10:00:00Z',
      closed_at: null,
      close_reason: null,
    },
    {
      id: 'trade-2',
      position_id: 'pos-1',
      trade_type: 'buy_stock',
      strike: null,
      expiration: null,
      premium: 0.0,
      unit_amount: 28.4,
      fees: 0.0,
      quantity: 100,
      opened_at: '2026-03-03T10:00:00Z',
      closed_at: null,
      close_reason: null,
    },
    {
      id: 'trade-3',
      position_id: 'pos-1',
      trade_type: 'dividend',
      strike: null,
      expiration: null,
      premium: 0.0,
      unit_amount: 42.0,
      fees: null,
      quantity: 0,
      opened_at: '2026-03-05T10:00:00Z',
      closed_at: null,
      close_reason: 'Qualified Div',
    },
  ],
};

function setupJournalMocks(page) {
  return Promise.all([
    page.route('**/api/journal/positions', (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ positions: [MOCK_EQUITY_POSITION] }),
        });
      }
      return route.continue();
    }),
    page.route('**/api/journal/positions/pos-1', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_EQUITY_POSITION),
      })
    ),
  ]);
}

test.describe('Equity journal rendering (issues #389 + #387) @e2e', () => {
  test('journal table renders equity + dividend rows with N/A, badges, and sub-type', async ({
    page,
  }) => {
    await setupJournalMocks(page);
    await page.goto('/journal?position=pos-1');
    await page.waitForLoadState('networkidle');

    const history = page.getByTestId('trade-history');
    await expect(history).toBeVisible();

    // The options row keeps the trade-row testid; equity rows use equity-row.
    await expect(page.getByTestId('trade-row')).toHaveCount(1);
    await expect(page.getByTestId('equity-row')).toHaveCount(2);

    // Equity kind badges.
    await expect(history).toContainText('Stock Buy');
    await expect(history).toContainText('Dividend');

    // buy_stock premium cell shows /sh affix; dividend shows total, no affix.
    await expect(history).toContainText('$28.40');
    await expect(history).toContainText('$42.00');
    await expect(history.getByText('/sh', { exact: true })).toHaveCount(1);

    // Dividend (#387): sub-type surfaces in the Close Reason cell.
    await expect(history).toContainText('Qualified Div');

    // N/A placeholders: buy_stock (strike, exp) + dividend (strike, exp, qty) = 5.
    await expect(page.getByTestId('na-placeholder')).toHaveCount(5);
  });

  test('dividend row never shows a 0 share count (#387)', async ({ page }) => {
    await setupJournalMocks(page);
    await page.goto('/journal?position=pos-1');
    await page.waitForLoadState('networkidle');

    const dividendRow = page.getByTestId('equity-row').filter({ hasText: 'Dividend' });
    await expect(dividendRow).toContainText('Qualified Div');
    // Qty cell renders the N/A placeholder, not "0".
    await expect(dividendRow.getByTestId('na-placeholder')).toHaveCount(3);
  });
});

// --- Unmatched-sell surfacing (AC3c / PRD #384 Q2) ---------------------------

// A buy + an unmatched sell (no prior shares): the sell is flagged in the
// preview and reported in the result instead of being silently dropped.
const UNMATCHED_PREVIEW = {
  account_number: '',
  trades: [
    {
      ticker: 'F', trade_type: 'buy_stock', strike: null, expiration: null,
      premium: 0.0, unit_amount: 11.0, fees: 0.0, quantity: 100,
      opened_at: '2026-03-01', close_reason: null, is_duplicate: false, is_unmatched: false,
    },
    {
      ticker: 'T', trade_type: 'sell_stock', strike: null, expiration: null,
      premium: 0.0, unit_amount: 18.0, fees: 0.65, quantity: 100,
      opened_at: '2026-03-28', close_reason: null, is_duplicate: false, is_unmatched: true,
    },
  ],
  total: 2, duplicates: 0, unmatched: 1, new_count: 1,
};

const UNMATCHED_RESULT = {
  imported: 1, skipped_duplicates: 0, positions_created: 1,
  skipped_unmatched: [{ ticker: 'T', opened_at: '2026-03-28', quantity: 100 }],
};

test.describe('Unmatched equity sells (AC3c / PRD #384 Q2) @e2e', () => {
  test.beforeEach(async ({ page }) => {
    await setupPreviewMocks(page, UNMATCHED_PREVIEW);
    await page.goto('/journal');
  });

  test('preview flags the unmatched sell and counts it', async ({ page }) => {
    await openCsvPreview(page);
    const badge = page.getByTestId('unmatched-badge');
    await expect(badge).toHaveCount(1);
    await expect(badge).toContainText('Unmatched');
    await expect(page.getByTestId('import-preview')).toContainText('1 unmatched');
  });

  test('result modal reports the skipped unmatched sell', async ({ page }) => {
    await page.route('**/api/journal/import/csv', (route) => {
      if (route.request().method() === 'POST') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(UNMATCHED_RESULT),
        });
      }
      return route.continue();
    });
    await openCsvPreview(page);
    await page.getByTestId('confirm-import-btn').click();
    const result = page.getByTestId('import-result');
    await expect(result).toBeVisible();
    const warning = page.getByTestId('import-unmatched-warning');
    await expect(warning).toBeVisible();
    await expect(warning).toContainText('Skipped 1 unmatched');
    await expect(warning).toContainText('T');
  });
});
