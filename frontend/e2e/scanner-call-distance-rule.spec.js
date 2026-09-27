import { test, expect } from '@playwright/test';

/**
 * E2E coverage for the covered-call distance rule (issue TBD) — one
 * threshold, one message.
 *
 *   E1  The strategy primer states the T% rule derived from the live
 *       call-distance filter value (default 10 → "at least 110%").
 *   E2  A near-pass fails_10pct_rule row names the dollar strike needed.
 *   E3  A negative distance reads "below", never "-5.4% above".
 *   E4  With empty human_reasons, the client fallback renders the rule
 *       sentence from the raw string (never the old "90%" copy).
 *
 * The scan endpoint is mocked; the raw strings use the backend's frozen
 * format: `fails_10pct_rule: strike {d}% above basis, requires {T}%
 * (strike $X, basis $B, min strike $Z)`.
 */

const RAW_1450 =
  'fails_10pct_rule: strike 9.8% above basis, requires 10.0% (strike $14.50, basis $13.21, min strike $14.53)';
const RAW_1250 =
  'fails_10pct_rule: strike -5.4% above basis, requires 10.0% (strike $12.50, basis $13.21, min strike $14.53)';

function scanPayload(rejected) {
  return {
    ticker: 'F',
    current_price: 12.71,
    strategy: 'covered_call',
    scan_time: '2026-05-20T12:00:00Z',
    earnings_date: null,
    iv_rank: null,
    recommendations: [],
    rejected,
    market_context: {},
  };
}

function setupMocks(page, payload) {
  return Promise.all([
    page.route('**/api/settings/health/schwab', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ configured: true, valid: true, error: null, token_expiry: null }),
      })
    ),
    page.route('**/api/options/scan', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(payload),
      })
    ),
  ]);
}

async function scanAndOpenRejected(page) {
  await page.goto('/options?ticker=F&strategy=covered_call&shares=100&cost_basis=13.21');
  await page.waitForLoadState('networkidle');
  await page.getByRole('button', { name: 'Scan Options' }).click();
  const disclosure = page.getByTestId('scanner-rejected-strikes');
  await expect(disclosure).toBeVisible();
  await page.getByTestId('scanner-rejected-strikes-toggle').click();
  return disclosure;
}

test.describe('Scanner — covered-call distance rule primer @smoke @e2e', () => {
  test('primer states the T% rule derived from the filter value', async ({ page }) => {
    await setupMocks(page, scanPayload([]));
    // Deterministic primer state — start collapsed.
    await page.goto('/options');
    await page.evaluate(() => {
      try {
        window.localStorage.removeItem('scanner-primer-collapsed-cc');
      } catch {
        // ignore
      }
    });
    await page.goto('/options?ticker=F&strategy=covered_call&shares=100&cost_basis=13.21');
    await page.waitForLoadState('networkidle');

    await page.getByTestId('scanner-strategy-primer-toggle').click();
    const whenToUse = page.getByTestId('scanner-strategy-primer-when-to-use');
    await expect(whenToUse).toContainText(
      'The 10% rule requires the strike to be at least 110% of your cost basis, so if your shares are called away, you lock in at least a 10% gain.'
    );
    await expect(whenToUse).not.toContainText('90%');

    // The primer tracks the same value the filter sends with the scan.
    await page.locator('#scanner-call-distance').fill('7.5');
    await expect(whenToUse).toContainText('The 7.5% rule');
    await expect(whenToUse).toContainText('at least 107.5% of your cost basis');
    await expect(whenToUse).toContainText('at least a 7.5% gain');
  });
});

test.describe('Scanner — covered-call distance rule rejections @e2e', () => {
  test('near-pass fails_10pct row shows the dollar strike needed', async ({ page }) => {
    await setupMocks(
      page,
      scanPayload([
        {
          strike: 14.5,
          expiration: '2026-06-26',
          rejection_reasons: [RAW_1450],
          human_reasons: [
            'Strike $14.50 is 9.8% above your $13.21 basis. Your 10% rule needs a strike of at least $14.53.',
          ],
        },
      ])
    );
    await scanAndOpenRejected(page);

    const row = page.getByTestId('scanner-rejected-strike-row').first();
    await expect(row.getByTestId('scanner-rejected-strike-badge-near-pass')).toBeVisible();
    await expect(row).toContainText(
      'Would pass — strike $14.50 is 9.8% above your $13.21 basis'
    );
    await expect(row).toContainText('at least $14.53');
    await expect(row).not.toContainText('fails_10pct_rule:');
  });

  test('negative distance renders "below"', async ({ page }) => {
    await setupMocks(
      page,
      scanPayload([
        {
          strike: 12.5,
          expiration: '2026-06-26',
          rejection_reasons: [RAW_1250],
          human_reasons: [
            'Strike $12.50 is 5.4% below your $13.21 basis. Your 10% rule needs a strike of at least $14.53.',
          ],
        },
      ])
    );
    await scanAndOpenRejected(page);

    const row = page.getByTestId('scanner-rejected-strike-row').first();
    await expect(row).toContainText('5.4% below your $13.21 basis');
    await expect(row).not.toContainText('-5.4%');
  });

  test('client fallback renders the rule sentence when human_reasons is empty', async ({ page }) => {
    await setupMocks(
      page,
      scanPayload([
        {
          strike: 14.5,
          expiration: '2026-06-26',
          rejection_reasons: [RAW_1450, 'low_open_interest: 12 < 50'],
          human_reasons: [],
        },
      ])
    );
    await scanAndOpenRejected(page);

    const row = page.getByTestId('scanner-rejected-strike-row').first();
    await expect(row).toContainText('2 reasons');
    await expect(row.locator('li').first()).toContainText(
      'needs a strike of at least $14.53'
    );
    await expect(row).not.toContainText('90%');
  });
});
