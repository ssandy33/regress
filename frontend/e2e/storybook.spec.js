import { test } from '@playwright/test';

/**
 * Issue #196 — Storybook infrastructure.
 *
 * The acceptance criteria for #196 are largely visual / browser-rendering
 * checks against a separate dev server (Storybook on :6006), and #196's
 * non-goals explicitly defer Chromatic / Playwright-against-Storybook visual
 * regression to a follow-up issue.
 *
 * Per CLAUDE.md ("If an AC is a manual/infrastructure step, document it in
 * the test file as a skipped test or comment explaining why it's not
 * automatable"), this file documents each AC and stubs the automation that
 * would cover it once visual-regression tooling lands.
 *
 * Manual verification performed for this PR:
 *
 *   1. `cd frontend && npm run storybook` — launches without errors on :6006.
 *   2. Browse to http://localhost:6006 → "Common / StatCard" — all variants
 *      (Default, Loading, Empty, Positive, Negative, WithTooltip) render.
 *   3. Toggle the theme switch in the toolbar — canvas flips between light
 *      and dark and StatCard's `dark:` Tailwind variants apply.
 *   4. `cd frontend && npm run build-storybook` — emits ./storybook-static
 *      without errors.
 *   5. `git status` shows storybook-static/ is gitignored (not staged).
 */

test.describe.skip('Storybook (issue #196) — deferred to follow-up', () => {
  test('storybook dev server boots on :6006', async () => {
    // Future: spawn `npm run storybook` and assert the iframe loads the
    // StatCard story. Skipped in Phase A — requires a separate dev server
    // process in CI, which is an explicit non-goal of #196.
  });

  test('StatCard Default variant renders with Tailwind tokens', async () => {
    // Future (Chromatic / Playwright-against-Storybook): navigate to the
    // iframe URL for the Default story, snapshot, diff.
  });

  test('Dark-mode toolbar toggle adds .dark to <html>', async () => {
    // Future: click the toolbar toggle, assert `html.classList` contains
    // `dark`, snapshot the canvas in both themes.
  });

  test('build-storybook produces a static bundle', async () => {
    // Future (non-blocking CI job): run `npm run build-storybook` and
    // assert ./storybook-static/index.html exists.
  });
});
