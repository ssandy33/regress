import { test, expect } from '@playwright/test';

const LINEAR_RESULT = {
  dates: ['2024-01-01', '2024-01-02', '2024-01-03'],
  values: [100, 101, 102],
  actual_values: [100, 101, 102],
  trend_line: [100, 101, 102],
  r_squared: 0.9876,
  slope: 0.0023,
  intercept: 99.5,
  p_value: 0.001,
  std_error: 0.0005,
  durbin_watson: 1.95,
  sample_size: 100,
  data_quality: { score: 95, gaps: 0, interpolated: 0 },
};

const ROLLING_RESULT = {
  dates: ['2024-01-01', '2024-01-02', '2024-01-03'],
  values: [100, 101, 102],
  slope_over_time: [0.001, 0.002, 0.003],
  r_squared_over_time: [0.8, 0.85, 0.9],
  sample_size: 100,
  data_quality: { score: 95, gaps: 0, interpolated: 0 },
};

const MULTI_FACTOR_RESULT = {
  dates: ['2024-01-01', '2024-01-02', '2024-01-03'],
  actual: [100, 101, 102],
  predicted: [100.1, 101.2, 101.9],
  residuals: [0.1, -0.2, 0.1],
  r_squared: 0.95,
  adjusted_r_squared: 0.94,
  f_statistic: 45.2,
  intercept: 0.5,
  durbin_watson: 2.01,
  coefficients: { SPY: 0.85, QQQ: 0.12 },
  p_values: { SPY: 0.001, QQQ: 0.04 },
  vif: { SPY: 1.2, QQQ: 1.2 },
  stationarity: {
    __dependent__: { is_stationary: true, p_value: 0.01 },
    SPY: { is_stationary: false, p_value: 0.15 },
  },
  sample_size: 100,
  data_quality: { score: 95, gaps: 0, interpolated: 0 },
};

const SEARCH_RESULTS = {
  results: [
    { identifier: 'SPY', name: 'S&P 500 ETF', source: 'yahoo', category: 'indices' },
  ],
};

/**
 * Mock all backend API endpoints so the page loads without a running backend.
 * Playwright route() intercepts browser-level fetches before Next.js rewrites proxy them.
 */
async function mockBackendAPIs(page, regressionOverrides = {}) {
  // Catch-all: intercept any /api/ request not matched by a more specific route
  await page.route('**/api/**', (route) => {
    const url = route.request().url();

    // Sessions — listSessions expects { sessions: [] }
    if (url.includes('/api/sessions')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ sessions: [] }) });
    }

    // Source health — checkSourceHealth expects { all_down: false, ... }
    if (url.includes('/api/health/sources')) {
      return route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ all_down: false, fred: { available: true }, yahoo: { available: true } }),
      });
    }

    // Settings health — checkFredHealth expects { configured: true }
    if (url.includes('/api/settings/health') || url.includes('/api/health')) {
      return route.fulfill({
        status: 200, contentType: 'application/json',
        body: JSON.stringify({ available: true, configured: true, error: null }),
      });
    }

    // Asset search
    if (url.includes('/api/assets/search')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(SEARCH_RESULTS) });
    }

    // Regression endpoints
    if (url.includes('/api/regression/linear')) {
      const result = regressionOverrides.linear || LINEAR_RESULT;
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(result) });
    }
    if (url.includes('/api/regression/rolling')) {
      const result = regressionOverrides.rolling || ROLLING_RESULT;
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(result) });
    }
    if (url.includes('/api/regression/multi-factor')) {
      const result = regressionOverrides.multiFactor || MULTI_FACTOR_RESULT;
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(result) });
    }

    // Fallback — let unmatched requests through (e.g. Next.js internal routes)
    return route.continue();
  });
}

async function selectAssetAndRun(page, { multiFactor = false } = {}) {
  const searchInput = page.getByPlaceholder('Search assets...').first();
  await searchInput.click();
  await searchInput.fill('SPY');
  await page.getByText('S&P 500 ETF').click();

  if (multiFactor) {
    const factorInput = page.getByPlaceholder('Add factors...');
    await factorInput.click();
    await factorInput.fill('SPY');
    await page.getByText('S&P 500 ETF').click();
  }

  await page.getByRole('button', { name: 'Run Analysis' }).click();
}

test.describe('Regression stats grouped display', () => {
  test.describe('Linear mode sections', () => {
    test('displays Model Fit, Trend, and Diagnostics section headers', async ({ page }) => {
      await mockBackendAPIs(page);
      await page.goto('/analysis');
      await page.waitForLoadState('networkidle');

      await selectAssetAndRun(page);

      await expect(page.getByText('Model Fit', { exact: true })).toBeVisible();
      await expect(page.getByText('Trend', { exact: true })).toBeVisible();
      await expect(page.getByText('Diagnostics', { exact: true })).toBeVisible();
    });

    test('Model Fit section contains R-Squared and P-Value cards', async ({ page }) => {
      await mockBackendAPIs(page);
      await page.goto('/analysis');
      await page.waitForLoadState('networkidle');

      await selectAssetAndRun(page);

      await expect(page.getByText('R-Squared')).toBeVisible();
      await expect(page.getByText('P-Value')).toBeVisible();
    });

    test('Trend section contains Slope, Intercept, and Std Error cards', async ({ page }) => {
      await mockBackendAPIs(page);
      await page.goto('/analysis');
      await page.waitForLoadState('networkidle');

      await selectAssetAndRun(page);

      await expect(page.getByText('Slope (per period)')).toBeVisible();
      await expect(page.getByText('Intercept')).toBeVisible();
      await expect(page.getByText('Std Error')).toBeVisible();
    });

    test('Diagnostics section hidden when durbin_watson is null', async ({ page }) => {
      await mockBackendAPIs(page, { linear: { ...LINEAR_RESULT, durbin_watson: null } });
      await page.goto('/analysis');
      await page.waitForLoadState('networkidle');

      await selectAssetAndRun(page);

      await expect(page.getByText('Model Fit', { exact: true })).toBeVisible();
      await expect(page.getByText('Trend', { exact: true })).toBeVisible();
      await expect(page.getByText('Diagnostics', { exact: true })).not.toBeVisible();
    });
  });

  test.describe('Rolling mode sections', () => {
    test('displays Current Window and Historical Range section headers', async ({ page }) => {
      await mockBackendAPIs(page);
      await page.goto('/analysis');
      await page.waitForLoadState('networkidle');

      await page.getByRole('button', { name: 'Rolling' }).click();
      await selectAssetAndRun(page);

      await expect(page.getByText('Current Window', { exact: true })).toBeVisible();
      await expect(page.getByText('Historical Range', { exact: true })).toBeVisible();
    });

    test('Current Window contains Current Slope and Current R-Squared', async ({ page }) => {
      await mockBackendAPIs(page);
      await page.goto('/analysis');
      await page.waitForLoadState('networkidle');

      await page.getByRole('button', { name: 'Rolling' }).click();
      await selectAssetAndRun(page);

      await expect(page.getByText('Current Slope', { exact: true })).toBeVisible();
      await expect(page.getByText('Current R-Squared', { exact: true })).toBeVisible();
    });

    test('Historical Range contains Avg/Min/Max stats', async ({ page }) => {
      await mockBackendAPIs(page);
      await page.goto('/analysis');
      await page.waitForLoadState('networkidle');

      await page.getByRole('button', { name: 'Rolling' }).click();
      await selectAssetAndRun(page);

      await expect(page.getByText('Avg Slope')).toBeVisible();
      await expect(page.getByText('Min Slope')).toBeVisible();
      await expect(page.getByText('Max Slope')).toBeVisible();
      await expect(page.getByText('Avg R-Squared')).toBeVisible();
      await expect(page.getByText('Min R-Squared')).toBeVisible();
      await expect(page.getByText('Max R-Squared')).toBeVisible();
    });
  });

  test.describe('Multi-Factor mode sections', () => {
    test('displays Summary, Coefficients, and Stationarity section headers', async ({ page }) => {
      await mockBackendAPIs(page);
      await page.goto('/analysis');
      await page.waitForLoadState('networkidle');

      await page.getByRole('button', { name: 'Multi-Factor' }).click();
      await selectAssetAndRun(page, { multiFactor: true });

      await expect(page.getByText('Summary', { exact: true })).toBeVisible();
      await expect(page.getByText('Coefficients', { exact: true })).toBeVisible();
      await expect(page.getByText('Stationarity', { exact: true })).toBeVisible();
    });

    test('Summary section contains stat cards', async ({ page }) => {
      await mockBackendAPIs(page);
      await page.goto('/analysis');
      await page.waitForLoadState('networkidle');

      await page.getByRole('button', { name: 'Multi-Factor' }).click();
      await selectAssetAndRun(page, { multiFactor: true });

      await expect(page.getByText('R-Squared', { exact: true })).toBeVisible();
      await expect(page.getByText('Adjusted R-Squared', { exact: true })).toBeVisible();
      await expect(page.getByText('F-Statistic', { exact: true })).toBeVisible();
    });

    test('Stationarity section hidden when stationarity is null', async ({ page }) => {
      await mockBackendAPIs(page, { multiFactor: { ...MULTI_FACTOR_RESULT, stationarity: null } });
      await page.goto('/analysis');
      await page.waitForLoadState('networkidle');

      await page.getByRole('button', { name: 'Multi-Factor' }).click();
      await selectAssetAndRun(page, { multiFactor: true });

      await expect(page.getByText('Summary', { exact: true })).toBeVisible();
      await expect(page.getByText('Coefficients', { exact: true })).toBeVisible();
      await expect(page.getByText('Stationarity', { exact: true })).not.toBeVisible();
    });
  });

  test.describe('Dark mode support', () => {
    test('section headers visible in dark mode for linear stats', async ({ page }) => {
      await mockBackendAPIs(page);
      await page.emulateMedia({ colorScheme: 'dark' });
      await page.goto('/analysis');
      await page.waitForLoadState('networkidle');

      await selectAssetAndRun(page);

      await expect(page.getByText('Model Fit', { exact: true })).toBeVisible();
      await expect(page.getByText('Trend', { exact: true })).toBeVisible();
      await expect(page.getByText('Diagnostics', { exact: true })).toBeVisible();
    });

    test('section headers visible in dark mode for rolling stats', async ({ page }) => {
      await mockBackendAPIs(page);
      await page.emulateMedia({ colorScheme: 'dark' });
      await page.goto('/analysis');
      await page.waitForLoadState('networkidle');

      await page.getByRole('button', { name: 'Rolling' }).click();
      await selectAssetAndRun(page);

      await expect(page.getByText('Current Window', { exact: true })).toBeVisible();
      await expect(page.getByText('Historical Range', { exact: true })).toBeVisible();
    });
  });
});
