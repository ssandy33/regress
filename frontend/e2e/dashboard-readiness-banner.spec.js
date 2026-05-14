import { test, expect } from '@playwright/test';

/**
 * E2E for issue #147 — Data Readiness Banner.
 *
 * Covers AC: severity ranking (worst-wins), hidden when all healthy, FRED
 * never surfaces on the dashboard, cache pill suppressed when total===0,
 * `role=alert` for error, `role=status` for warn, session-only dismiss,
 * reload restores the banner (no persistence).
 */

const BASE_STATUS = {
  schwab: { configured: true, valid: true, expires_at: '2026-08-01T00:00:00+00:00' },
  fred: { configured: true, valid: true },
  cache: { fresh: 12, stale: 0, very_stale: 0, total: 12 },
  journal: { positions_count: 1 },
};

const BASE_PAYLOAD = {
  generated_at: '2026-05-12T13:42:00+00:00',
  status: BASE_STATUS,
  kpis: {
    open_positions: 1,
    open_positions_breakdown: { stock: 0, csp: 0, cc: 0, wheel: 1, holding: 0 },
    notional_value: 1000,
    notional_change_pct: 0,
    open_legs: 1,
    open_legs_breakdown: { puts: 1, calls: 0 },
    unrealized_pl: 0,
    unrealized_pl_pct: 0,
  },
  positions: [
    {
      id: 'pos-aapl',
      ticker: 'AAPL',
      shares: 100,
      strategy: 'wheel',
      adjusted_cost_basis: 17240.0,
      current_price: 175.42,
      notional: 17542.0,
      unrealized_pl: 302.0,
      open_legs_count: 1,
    },
  ],
  open_legs: [],
  upcoming_expirations: [],
  recent_activity: [],
  data_meta: {
    is_stale: false,
    fetched_at: '2026-05-12T13:42:00+00:00',
    sources_unavailable: [],
  },
};

function withStatus(payload, overrides) {
  return { ...payload, status: { ...payload.status, ...overrides } };
}

function mockDashboard(page, payload) {
  return page.route('**/api/dashboard', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(payload),
    })
  );
}

test.describe('DataReadinessBanner', () => {
  test('hidden when all sources healthy', async ({ page }) => {
    await mockDashboard(page, BASE_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    await expect(page.getByTestId('data-readiness-banner')).toHaveCount(0);
  });

  test('renders error banner with role=alert when Schwab disconnected', async ({ page }) => {
    await mockDashboard(
      page,
      withStatus(BASE_PAYLOAD, {
        schwab: { configured: false, valid: false, expires_at: null },
      })
    );
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const banner = page.getByTestId('data-readiness-banner');
    await expect(banner).toBeVisible();
    await expect(banner).toHaveAttribute('role', 'alert');
    await expect(banner).toHaveAttribute('data-severity', 'error');
    // Glyph + text both encode severity (not color alone)
    await expect(banner).toContainText('⛔');
    await expect(banner).toContainText('Schwab disconnected');
  });

  test('renders warn banner with role=status when cache is stale', async ({ page }) => {
    await mockDashboard(
      page,
      withStatus(BASE_PAYLOAD, {
        cache: { fresh: 8, stale: 3, very_stale: 0, total: 11 },
      })
    );
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const banner = page.getByTestId('data-readiness-banner');
    await expect(banner).toBeVisible();
    await expect(banner).toHaveAttribute('role', 'status');
    await expect(banner).toHaveAttribute('data-severity', 'warn');
    await expect(banner).toContainText('⚠');
    await expect(banner).toContainText('stale');
  });

  test('error outranks warn when both conditions hold', async ({ page }) => {
    // Schwab disconnected (error) + cache stale (warn) → error wins.
    await mockDashboard(
      page,
      withStatus(BASE_PAYLOAD, {
        schwab: { configured: false, valid: false, expires_at: null },
        cache: { fresh: 8, stale: 3, very_stale: 0, total: 11 },
      })
    );
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const banner = page.getByTestId('data-readiness-banner');
    await expect(banner).toHaveAttribute('data-severity', 'error');
    await expect(banner).toContainText('Schwab disconnected');
  });

  test('cache very-stale renders as error (red) over schwab expiring (warn)', async ({ page }) => {
    // Token expiring < 2 days (warn) + cache very_stale (error) → error wins.
    const soon = new Date(Date.now() + 12 * 60 * 60 * 1000).toISOString();
    await mockDashboard(
      page,
      withStatus(BASE_PAYLOAD, {
        schwab: { configured: true, valid: true, expires_at: soon },
        cache: { fresh: 5, stale: 0, very_stale: 2, total: 7 },
      })
    );
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const banner = page.getByTestId('data-readiness-banner');
    await expect(banner).toHaveAttribute('data-severity', 'error');
    await expect(banner).toContainText('very stale');
  });

  test('warn banner is hidden for a fresh 7-day Schwab token', async ({ page }) => {
    // Regression: Schwab refresh tokens last 7 days from issuance, so the
    // banner must stay silent immediately after re-auth. Previously the
    // threshold matched the lifetime and fired permanently.
    const sevenDays = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString();
    await mockDashboard(
      page,
      withStatus(BASE_PAYLOAD, {
        schwab: { configured: true, valid: true, expires_at: sevenDays },
      })
    );
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    await expect(page.getByTestId('data-readiness-banner')).toHaveCount(0);
  });

  test('FRED missing does NOT surface on the dashboard banner', async ({ page }) => {
    // FRED missing on its own should not raise the banner.
    await mockDashboard(
      page,
      withStatus(BASE_PAYLOAD, {
        fred: { configured: false, valid: false },
      })
    );
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    await expect(page.getByTestId('data-readiness-banner')).toHaveCount(0);
  });

  test('cache pill is hidden when cache total === 0', async ({ page }) => {
    await mockDashboard(
      page,
      withStatus(BASE_PAYLOAD, {
        cache: { fresh: 0, stale: 0, very_stale: 0, total: 0 },
      })
    );
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    await expect(page.getByTestId('status-pill-cache')).toHaveCount(0);
    // Other pills still render
    await expect(page.getByTestId('status-pill-schwab')).toBeVisible();
  });

  test('primary CTA navigates to settings when Schwab disconnected', async ({ page }) => {
    await mockDashboard(
      page,
      withStatus(BASE_PAYLOAD, {
        schwab: { configured: false, valid: false, expires_at: null },
      })
    );
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    await page.getByTestId('data-readiness-banner-cta-primary').click();
    await page.waitForURL(/\/settings/);
    expect(page.url()).toContain('/settings');
  });

  test('dismiss hides banner for the session; reload restores it', async ({ page }) => {
    const payload = withStatus(BASE_PAYLOAD, {
      schwab: { configured: false, valid: false, expires_at: null },
    });
    await mockDashboard(page, payload);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const banner = page.getByTestId('data-readiness-banner');
    await expect(banner).toBeVisible();

    await page.getByTestId('data-readiness-banner-dismiss').click();
    await expect(page.getByTestId('data-readiness-banner')).toHaveCount(0);

    // Reload — banner reappears because dismiss is session-only (no
    // localStorage persistence per AC §14.1).
    await page.reload();
    await page.waitForLoadState('networkidle');
    await expect(page.getByTestId('data-readiness-banner')).toBeVisible();
  });

  test('does not persist dismissal to localStorage', async ({ page }) => {
    const payload = withStatus(BASE_PAYLOAD, {
      schwab: { configured: false, valid: false, expires_at: null },
    });
    await mockDashboard(page, payload);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    await page.getByTestId('data-readiness-banner-dismiss').click();

    const storageKeys = await page.evaluate(() => Object.keys(window.localStorage));
    // No key should contain 'banner' or 'readiness' (case-insensitive).
    const matching = storageKeys.filter((k) => /banner|readiness/i.test(k));
    expect(matching).toEqual([]);
  });
});
