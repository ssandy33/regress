import { test, expect } from '@playwright/test';

const MOCK_POSITION = {
  id: 'pos-1',
  ticker: 'AAPL',
  shares: 100,
  broker_cost_basis: 15000.0,
  status: 'open',
  strategy: 'wheel',
  opened_at: '2025-01-15T10:00:00Z',
  closed_at: null,
  notes: null,
  total_premiums: 350.0,
  adjusted_cost_basis: 14650.0,
  min_compliant_cc_strike: 161.15,
  trades: [
    {
      id: 'trade-1',
      position_id: 'pos-1',
      trade_type: 'sell_put',
      strike: 145.0,
      expiration: '2025-02-21',
      premium: 2.0,
      fees: 0.65,
      quantity: 1,
      opened_at: '2025-01-15T10:00:00Z',
      closed_at: '2025-02-01T10:00:00Z',
      close_reason: 'fifty_pct_target',
    },
    {
      id: 'trade-2',
      position_id: 'pos-1',
      trade_type: 'sell_call',
      strike: 165.0,
      expiration: '2025-03-21',
      premium: 1.5,
      fees: 0.65,
      quantity: 1,
      opened_at: '2025-02-05T10:00:00Z',
      closed_at: null,
      close_reason: null,
    },
  ],
};

function setupMocks(page) {
  return Promise.all([
    page.route('**/api/journal/positions', (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ positions: [MOCK_POSITION] }),
        });
      }
      if (route.request().method() === 'POST') {
        const body = route.request().postDataJSON();
        return route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({
            id: 'pos-new',
            ...body,
            status: 'open',
            closed_at: null,
            total_premiums: 0,
            adjusted_cost_basis: body.broker_cost_basis,
            min_compliant_cc_strike: (body.broker_cost_basis / (body.shares || 100)) * 1.1,
            trades: [],
          }),
        });
      }
      return route.continue();
    }),
    page.route('**/api/journal/positions/pos-1', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_POSITION),
      })
    ),
    page.route('**/api/journal/trades', (route) => {
      if (route.request().method() === 'POST') {
        const body = route.request().postDataJSON();
        return route.fulfill({
          status: 201,
          contentType: 'application/json',
          body: JSON.stringify({ id: 'trade-new', ...body }),
        });
      }
      return route.continue();
    }),
    page.route('**/api/journal/trades/*', (route) => {
      if (route.request().method() === 'DELETE') {
        return route.fulfill({ status: 204 });
      }
      return route.continue();
    }),
  ]);
}

test.describe('Journal page', () => {
  test('renders positions table with data', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/journal');
    await page.waitForLoadState('networkidle');

    const table = page.getByTestId('positions-table');
    await expect(table).toBeVisible();
    await expect(table).toContainText('AAPL');
    await expect(table).toContainText('Ticker');
    await expect(table).toContainText('Broker Basis');
    await expect(table).toContainText('Adjusted Basis');
    await expect(table).toContainText('Min CC Strike');
  });

  test('position row shows computed fields', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/journal');
    await page.waitForLoadState('networkidle');

    const row = page.getByTestId('position-row').first();
    await expect(row).toContainText('$350.00');
    await expect(row).toContainText('$14650.00');
    await expect(row).toContainText('$161.15');
  });

  test('status badges render correctly', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/journal');
    await page.waitForLoadState('networkidle');

    const badge = page.getByTestId('status-badge').first();
    await expect(badge).toContainText('open');
    await expect(badge).toHaveClass(/bg-green-100/);
  });

  test('clicking position shows trade history', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/journal');
    await page.waitForLoadState('networkidle');

    await page.getByTestId('position-row').first().click();
    const history = page.getByTestId('trade-history');
    await expect(history).toBeVisible();

    const tradeRows = page.getByTestId('trade-row');
    await expect(tradeRows).toHaveCount(2);
    await expect(history).toContainText('Sell Put');
    await expect(history).toContainText('Sell Call');
  });

  test('trade entry form creates trade', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/journal');
    await page.waitForLoadState('networkidle');

    await page.getByTestId('position-row').first().click();
    await page.getByTestId('add-trade-btn').click();

    const form = page.getByTestId('trade-entry-form');
    await expect(form).toBeVisible();

    await form.locator('input[name="strike"]').fill('150');
    await form.locator('input[name="expiration"]').fill('2025-04-18');
    await form.locator('input[name="premium"]').fill('1.75');

    const [request] = await Promise.all([
      page.waitForRequest('**/api/journal/trades'),
      form.getByRole('button', { name: 'Save Trade' }).click(),
    ]);
    expect(request.method()).toBe('POST');
    const body = request.postDataJSON();
    expect(body.strike).toBe(150);
    expect(body.premium).toBe(1.75);
  });

  test('new position form works', async ({ page }) => {
    await setupMocks(page);
    await page.goto('/journal');
    await page.waitForLoadState('networkidle');

    await page.getByTestId('new-position-btn').click();
    const form = page.getByTestId('position-form');
    await expect(form).toBeVisible();

    await form.locator('input[name="ticker"]').fill('MSFT');
    await form.locator('input[name="broker_cost_basis"]').fill('20000');

    const [request] = await Promise.all([
      page.waitForRequest('**/api/journal/positions'),
      form.getByRole('button', { name: 'Create Position' }).click(),
    ]);
    expect(request.method()).toBe('POST');
    const body = request.postDataJSON();
    expect(body.ticker).toBe('MSFT');
    expect(body.broker_cost_basis).toBe(20000);
  });
});
