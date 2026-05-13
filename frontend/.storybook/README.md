# Storybook

Opt-in dev tooling for previewing and iterating on UI components in isolation.
This is the canonical mock format for the designer agent — replaces ASCII
mockups in `frontend/design-specs/` going forward.

CI does **not** depend on Storybook. `npm run build-storybook` is not part of
the PR build today; visual regression and a11y addons are deliberately
deferred (see follow-up issues).

## Run it

From `frontend/`:

```bash
npm run storybook        # dev server on http://localhost:6006
npm run build-storybook  # static site to ./storybook-static (gitignored)
```

## Conventions

- **Naming**: `*.stories.jsx` (or `.tsx` later), colocated next to the
  component file. Example: `components/common/StatCard.stories.jsx` lives next
  to `components/common/StatCard.jsx`.
- **Title**: `'<Area>/<ComponentName>'`, e.g. `'Common/StatCard'`,
  `'Dashboard/KPIRow'`. Keep the hierarchy shallow.
- **Variants represent real UI states** — `Default`, `Loading`, `Empty`,
  `Error`, `Positive` / `Negative`, etc. Don't fan out every imaginable prop
  combination; aim for the states a user can actually see.
- **Fixture data only**. Stories must not call the backend, hit
  `/api/*`, or pull from real `axios`/`fetch` clients. If a component
  needs data, hand it static props or wrap it in a story-local provider.
- **Imports**: import the component under test with a relative path
  (`./StatCard`) since stories are colocated. Use the `@/` alias only when
  importing from elsewhere in the tree.

## Dark mode

The toolbar exposes a theme toggle (light / dark) wired via
`@storybook/addon-themes` → `withThemeByClassName`. It adds `.dark` to the
`<html>` element, which matches what `context/ThemeContext.jsx` does in the
running app. Every story should render correctly in both themes.

## Stack notes (Tailwind v4 + Next 16)

- The framework is `@storybook/nextjs-vite` (Storybook 10's Vite-based Next
  integration). The legacy webpack `@storybook/nextjs` was not selected by
  `storybook init` against this project — Vite is the supported path for
  Next 15+ / React 19 in Storybook 10.
- `preview.js` imports `../app/globals.css` directly. Tailwind v4's
  `@import "tailwindcss"` + `@custom-variant dark` declarations are picked up
  by the project's PostCSS config (`postcss.config.mjs` →
  `@tailwindcss/postcss`) and applied to the Storybook canvas without
  modification.
- No Storybook-specific Tailwind config was needed.

## What's intentionally not here (Phase A)

- `@storybook/addon-a11y` — defer to a follow-up issue.
- `@storybook/addon-viewport` — defer.
- `@chromatic-com/storybook` / Chromatic — visual regression is a separate
  follow-up.
- `@storybook/addon-vitest` / test runner — Playwright e2e against the real
  app is the project's automated UI test surface.
- Backfill stories for other components — only `StatCard` ships in Phase A
  as the reference pattern. New stories land issue-by-issue.

## Automated test coverage (per CLAUDE.md)

Most ACs for issue #196 are visual / browser-rendering checks (story shows
all 5 variants, dark-mode toolbar toggles the canvas, real Tailwind classes
apply). Those are not fully automatable in Phase A without bringing in
Chromatic or Playwright-against-Storybook, both of which are explicit
non-goals.

The mechanically verifiable AC — `npm run build-storybook` succeeds — is
covered by:

- A Playwright spec stub at `frontend/e2e/storybook.spec.js` that documents
  the manual verification steps and a skipped placeholder for the future
  visual-regression run.
- Local pre-commit verification: this PR was only landed after
  `npm run storybook` started cleanly on :6006 and `npm run build-storybook`
  produced `storybook-static/` without errors.
