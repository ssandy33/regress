import { test, expect } from '@playwright/test';

/**
 * Mock journal positions used to seed `useJournal()` on the Settings page.
 * The reconcile section is gated on ``positions.length > 0`` so the empty
 * variant of this seed is used for the empty-state test.
 */
const SEEDED_POSITIONS = [
  {
    id: 'pos-mara',
    ticker: 'MARA',
    shares: 100,
    broker_cost_basis: 0.0,
    status: 'open',
    strategy: 'wheel',
    opened_at: '2026-01-01T00:00:00Z',
    closed_at: null,
    notes: null,
    total_premiums: 0,
    adjusted_cost_basis: 0,
    min_compliant_cc_strike: 0,
    trades: [],
  },
];

const PREVIEW_RESPONSE = {
  dry_run: true,
  positions_processed: 1,
  trades_stamped: 2,
  status_changes: 1,
  share_corrections: 1,
  basis_corrections: 0,
  strategy_changes: 1,
  errors: 0,
  per_position: [
    {
      ticker: 'MARA',
      status_before: 'open',
      status_after: 'closed',
      shares_before: 100,
      shares_after: 0,
      basis_before: 0.0,
      basis_after: 0.0,
      strategy_before: 'wheel',
      strategy_after: 'csp',
      closed_at_before: null,
      closed_at_after: '2026-03-20',
      legs_consumed: 2,
    },
  ],
};

const APPLY_RESPONSE = {
  ...PREVIEW_RESPONSE,
  dry_run: false,
};

function setupSettingsMocks(page, { positions = SEEDED_POSITIONS } = {}) {
  return Promise.all([
    page.route('**/api/journal/positions*', (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ positions }),
        });
      }
      return route.continue();
    }),
    page.route('**/api/journal/reconcile', (route) => {
      if (route.request().method() === 'POST') {
        const body = route.request().postDataJSON() || {};
        const isDryRun = body.dry_run !== false; // default true
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify(isDryRun ? PREVIEW_RESPONSE : APPLY_RESPONSE),
        });
      }
      return route.continue();
    }),
  ]);
}

test.describe('Settings → Reconcile journal @e2e', () => {
  test('renders above Danger Zone with both buttons enabled', async ({ page }) => {
    await setupSettingsMocks(page);

    await page.goto('/settings');
    await page.waitForLoadState('networkidle');

    const reconcile = page.getByTestId('reconcile-journal');
    const danger = page.getByTestId('danger-zone');
    await expect(reconcile).toBeVisible();
    await expect(danger).toBeVisible();

    // The Reconcile section must render above Danger Zone (issue #139 AC-4).
    const reconcileBox = await reconcile.boundingBox();
    const dangerBox = await danger.boundingBox();
    expect(reconcileBox).not.toBeNull();
    expect(dangerBox).not.toBeNull();
    expect(reconcileBox.y).toBeLessThan(dangerBox.y);

    // Both buttons enabled independently — Apply does not require a prior
    // Preview run.
    await expect(page.getByTestId('reconcile-preview-btn')).toBeEnabled();
    await expect(page.getByTestId('reconcile-apply-btn')).toBeEnabled();
  });

  test('Preview renders the per-position before/after table', async ({ page }) => {
    await setupSettingsMocks(page);
    await page.goto('/settings');
    await page.waitForLoadState('networkidle');

    const previewBtn = page.getByTestId('reconcile-preview-btn');
    await previewBtn.click();

    const table = page.getByTestId('reconcile-table');
    await expect(table).toBeVisible();

    const row = page.getByTestId('reconcile-row').first();
    await expect(row).toContainText('MARA');
    // Status before/after.
    await expect(row).toContainText('open');
    await expect(row).toContainText('closed');
    // Shares before/after.
    await expect(row).toContainText('100');
    await expect(row).toContainText('0');
    // Strategy before/after.
    await expect(row).toContainText('wheel');
    await expect(row).toContainText('csp');
  });

  test('Apply opens confirm dialog and surfaces toast on success', async ({ page }) => {
    await setupSettingsMocks(page);
    await page.goto('/settings');
    await page.waitForLoadState('networkidle');

    await page.getByTestId('reconcile-apply-btn').click();
    const dialog = page.getByTestId('confirm-dialog');
    await expect(dialog).toBeVisible();
    await expect(dialog).toContainText('Reconcile');
    await expect(dialog).toContainText('recompute position state from the trade ledger');

    const [request] = await Promise.all([
      page.waitForRequest((req) =>
        req.url().includes('/api/journal/reconcile')
        && req.method() === 'POST'
        && (req.postDataJSON() || {}).dry_run === false,
      ),
      page.getByTestId('confirm-dialog-confirm').click(),
    ]);
    expect(request.method()).toBe('POST');

    // Toast confirms the result counts (issue #139 AC-8).
    const toastLocator = page.locator('text=/Reconciled \\d+ positions/').first();
    await expect(toastLocator).toBeVisible();
  });

  test('empty journal disables both buttons and shows an empty state', async ({ page }) => {
    await setupSettingsMocks(page, { positions: [] });
    await page.goto('/settings');
    await page.waitForLoadState('networkidle');

    await expect(page.getByTestId('reconcile-empty-state')).toBeVisible();
    await expect(page.getByTestId('reconcile-empty-state')).toContainText('No positions to reconcile');
    await expect(page.getByTestId('reconcile-preview-btn')).toBeDisabled();
    await expect(page.getByTestId('reconcile-apply-btn')).toBeDisabled();
  });
});
