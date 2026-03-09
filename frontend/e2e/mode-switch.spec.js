import { test, expect } from '@playwright/test';

const MODES = [
  { name: 'Linear', description: 'Single variable regression' },
  { name: 'Multi-Factor', description: 'Multiple independents' },
  { name: 'Rolling', description: 'Time-windowed analysis' },
  { name: 'Compare', description: 'Side-by-side assets' },
];

test.describe('Regression mode selector bar', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  // AC: Mode selector renders as a full-width bar above the sidebar + main content area
  test('mode bar renders above sidebar and main content', async ({ page }) => {
    // All 4 mode buttons should be visible
    for (const { name } of MODES) {
      await expect(page.getByRole('button', { name, exact: false })).toBeVisible();
    }

    // The mode bar should come before the sidebar in DOM order
    // Mode bar is a direct child of the top-level flex-col container, before the flex row
    const modeButton = page.getByRole('button', { name: 'Linear', exact: false });
    const sidebar = page.locator('aside');

    const modeBarY = await modeButton.boundingBox();
    const sidebarY = await sidebar.boundingBox();
    expect(modeBarY.y).toBeLessThan(sidebarY.y);
  });

  // AC: All 4 modes (Linear, Multi-Factor, Rolling, Compare) are selectable
  test('all 4 modes are selectable', async ({ page }) => {
    for (const { name } of MODES) {
      const btn = page.getByRole('button', { name, exact: false });
      await btn.click();

      // Active mode should have aria-pressed="true"
      await expect(btn).toHaveAttribute('aria-pressed', 'true');

      // Other modes should have aria-pressed="false"
      for (const { name: otherName } of MODES) {
        if (otherName !== name) {
          await expect(
            page.getByRole('button', { name: otherName, exact: false })
          ).toHaveAttribute('aria-pressed', 'false');
        }
      }
    }
  });

  // AC: Active mode is visually distinct (highlighted)
  test('active mode has distinct visual styling', async ({ page }) => {
    for (const { name } of MODES) {
      const btn = page.getByRole('button', { name, exact: false });
      await btn.click();

      // Active button should have the blue border and background tint
      await expect(btn).toHaveClass(/border-blue-600/);
      await expect(btn).toHaveClass(/bg-blue-50/);
    }
  });

  // AC: Sidebar no longer contains the mode selector
  test('sidebar does not contain mode selector buttons', async ({ page }) => {
    const sidebar = page.locator('aside');

    // The sidebar should not have any of the mode buttons
    for (const { name } of MODES) {
      await expect(sidebar.getByRole('button', { name, exact: true })).not.toBeVisible();
    }
  });

  // AC: Works in both light and dark mode
  test('mode bar works in dark mode', async ({ page }) => {
    // Emulate dark color scheme
    await page.emulateMedia({ colorScheme: 'dark' });
    await page.waitForTimeout(300);

    // All mode buttons should still be visible and clickable
    for (const { name } of MODES) {
      const btn = page.getByRole('button', { name, exact: false });
      await expect(btn).toBeVisible();
      await btn.click();
      await expect(btn).toHaveAttribute('aria-pressed', 'true');
    }
  });

  // AC: Sidebar collapse/expand still works
  test('sidebar collapse and expand still works', async ({ page }) => {
    const sidebar = page.locator('aside');
    await expect(sidebar).toBeVisible();

    // Collapse sidebar
    const collapseBtn = page.getByRole('button', { name: 'Collapse sidebar' });
    await collapseBtn.click();
    await expect(sidebar).not.toBeVisible();

    // Expand sidebar
    const expandBtn = page.getByRole('button', { name: 'Expand sidebar' });
    await expandBtn.click();
    await expect(sidebar).toBeVisible();

    // Mode bar should still be functional after collapse/expand
    const rollingBtn = page.getByRole('button', { name: 'Rolling', exact: false });
    await rollingBtn.click();
    await expect(rollingBtn).toHaveAttribute('aria-pressed', 'true');
  });

  // AC: All existing regression functionality unchanged
  test('switching modes shows empty state (not a blank screen)', async ({ page }) => {
    await expect(page.getByText('Select an asset and run analysis')).toBeVisible();

    for (const { name } of MODES.slice(1)) {
      await page.getByRole('button', { name, exact: false }).click();
      await expect(page.getByText('Select an asset and run analysis')).toBeVisible();
    }
  });

  test('switching back to Linear after visiting other modes still works', async ({ page }) => {
    await page.getByRole('button', { name: 'Rolling', exact: false }).click();
    await page.getByRole('button', { name: 'Compare', exact: false }).click();
    await page.getByRole('button', { name: 'Linear', exact: false }).click();

    await expect(page.getByText('Select an asset and run analysis')).toBeVisible();
    await expect(
      page.getByRole('button', { name: 'Linear', exact: false })
    ).toHaveAttribute('aria-pressed', 'true');
  });

  test('no console errors when switching modes', async ({ page }) => {
    const errors = [];
    page.on('pageerror', (err) => errors.push(err.message));

    for (const { name } of MODES) {
      await page.getByRole('button', { name, exact: false }).click();
      await page.waitForTimeout(300);
    }

    expect(errors).toEqual([]);
  });

  test('rapid mode switching does not crash', async ({ page }) => {
    for (let i = 0; i < 3; i++) {
      for (const { name } of MODES) {
        await page.getByRole('button', { name, exact: false }).click();
      }
    }

    await expect(page.getByText('Select an asset and run analysis')).toBeVisible();
  });
});
