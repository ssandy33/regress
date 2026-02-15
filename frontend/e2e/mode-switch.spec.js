import { test, expect } from '@playwright/test';

const MODES = ['Linear', 'Multi', 'Rolling', 'Compare'];

test.describe('Regression mode switching', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('page does not go blank when cycling through all modes', async ({ page }) => {
    for (const mode of MODES) {
      await page.getByRole('button', { name: mode }).click();

      // The page should never be blank — either EmptyState or results should be visible
      const body = page.locator('body');
      await expect(body).not.toHaveText('');

      // The mode button should be active (has the blue background class)
      const btn = page.getByRole('button', { name: mode, exact: true });
      await expect(btn).toHaveClass(/bg-blue-600/);
    }
  });

  test('switching modes shows empty state (not a blank screen)', async ({ page }) => {
    // Start on Linear — should show empty state
    await expect(page.getByText('Select an asset and run analysis')).toBeVisible();

    // Switch to each mode and verify empty state persists (no stale result crash)
    for (const mode of MODES.slice(1)) {
      await page.getByRole('button', { name: mode }).click();
      await expect(page.getByText('Select an asset and run analysis')).toBeVisible();
    }
  });

  test('switching back to Linear after visiting other modes still works', async ({ page }) => {
    await page.getByRole('button', { name: 'Rolling' }).click();
    await page.getByRole('button', { name: 'Compare' }).click();
    await page.getByRole('button', { name: 'Linear' }).click();

    await expect(page.getByText('Select an asset and run analysis')).toBeVisible();
    await expect(page.getByRole('button', { name: 'Linear', exact: true })).toHaveClass(/bg-blue-600/);
  });

  test('no console errors when switching modes', async ({ page }) => {
    const errors = [];
    page.on('pageerror', (err) => errors.push(err.message));

    for (const mode of MODES) {
      await page.getByRole('button', { name: mode }).click();
      // Small pause to let React re-render
      await page.waitForTimeout(300);
    }

    expect(errors).toEqual([]);
  });

  test('rapid mode switching does not crash', async ({ page }) => {
    // Click through all modes rapidly without waiting
    for (let i = 0; i < 3; i++) {
      for (const mode of MODES) {
        await page.getByRole('button', { name: mode }).click();
      }
    }

    // Page should still be functional after rapid switching
    await expect(page.getByText('Select an asset and run analysis')).toBeVisible();
  });
});
