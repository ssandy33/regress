import { test, expect } from '@playwright/test';

/**
 * Issue #117 — verifies the in-app dark-mode toggle actually drives Tailwind
 * `dark:` variants across the UI.
 *
 * The bug fixed by this test: Tailwind v4's default `dark:` variant is
 * media-query-based (`prefers-color-scheme: dark`), but `ThemeContext.jsx`
 * is class-based (toggles `.dark` on <html>). Without the
 * `@custom-variant dark (.dark, .dark *)` declaration in `globals.css`,
 * the body would change but every component-level `dark:bg-*` etc. stayed
 * in its light style.
 *
 * Test strategy: pin the browser to OS-light preference (so `prefers-color
 * -scheme: dark` is false) and verify the toggle still drives the variants.
 */

/**
 * Returns the perceived brightness (0..255) of an element's computed
 * background-color. Robust to whether the browser serializes the value as
 * `rgb(...)` or the newer `lab(...)` / `oklch(...)` color-managed forms.
 *
 * Strategy: render the element's bg into an off-screen canvas and read
 * back the pixel — sidesteps every CSS color string format.
 */
async function bgLuminance(locator) {
  return locator.evaluate((el) => {
    const bg = getComputedStyle(el).backgroundColor;
    const canvas = document.createElement('canvas');
    canvas.width = 1; canvas.height = 1;
    const ctx = canvas.getContext('2d');
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, 1, 1);
    const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
    return 0.299 * r + 0.587 * g + 0.114 * b;
  });
}

test.describe('Dark mode toggle (#117)', () => {
  test('toggles every dark: variant when OS prefers light', async ({ browser }) => {
    const ctx = await browser.newContext({ colorScheme: 'light' });
    const page = await ctx.newPage();

    // Clear any stored theme so initial state is purely OS-driven (light).
    await page.addInitScript(() => {
      try { window.localStorage.removeItem('theme'); } catch {}
    });

    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const html = page.locator('html');
    const header = page.locator('header').first();
    await expect(header).toBeVisible();

    // Initial: OS light + no localStorage → ThemeContext computes `dark=false`.
    await expect(html).not.toHaveClass(/(?:^|\s)dark(?:\s|$)/);
    expect(await bgLuminance(header)).toBeGreaterThan(200);

    // Toggle to dark.
    await page.getByTestId('dark-mode-toggle').click();
    await expect(html).toHaveClass(/(?:^|\s)dark(?:\s|$)/);
    // The dark: variant must fire — header swaps to slate-800. This is the
    // assertion that catches the original bug; without `@custom-variant dark`
    // the header stays bg-white even though `<html class="dark">`.
    expect(await bgLuminance(header)).toBeLessThan(80);

    // Toggle back to light.
    await page.getByTestId('dark-mode-toggle').click();
    await expect(html).not.toHaveClass(/(?:^|\s)dark(?:\s|$)/);
    expect(await bgLuminance(header)).toBeGreaterThan(200);

    await ctx.close();
  });

  test('toggle works in the reverse direction when OS prefers dark', async ({ browser }) => {
    const ctx = await browser.newContext({ colorScheme: 'dark' });
    const page = await ctx.newPage();

    await page.addInitScript(() => {
      try { window.localStorage.removeItem('theme'); } catch {}
    });

    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const html = page.locator('html');
    const header = page.locator('header').first();
    await expect(header).toBeVisible();

    // Initial: OS dark + no localStorage → ThemeContext computes `dark=true`.
    await expect(html).toHaveClass(/(?:^|\s)dark(?:\s|$)/);
    expect(await bgLuminance(header)).toBeLessThan(80);

    // Toggle to light — must override the OS dark preference because
    // `dark:` variants are now class-keyed, not media-query-keyed.
    await page.getByTestId('dark-mode-toggle').click();
    await expect(html).not.toHaveClass(/(?:^|\s)dark(?:\s|$)/);
    expect(await bgLuminance(header)).toBeGreaterThan(200);

    await ctx.close();
  });
});
