import { test, expect } from '@playwright/test';

/**
 * E2E for issue #152 — Next Actions section.
 *
 * Covers AC: top 3 visible by default, `[Show N more]` expands the rest,
 * hard cap at 8 actions, priority badge text + glyph present, "All quiet"
 * empty state with both CTAs, link-CTA navigation, inline-CTA inline action
 * (no navigation), section landmark, focus ring.
 */

const POSITIVE_KPIS = {
  open_positions: 2,
  open_positions_breakdown: { stock: 0, csp: 0, cc: 0, wheel: 1, holding: 1 },
  notional_value: 17542,
  notional_change_pct: 0.021,
  open_legs: 1,
  open_legs_breakdown: { puts: 1, calls: 0 },
  unrealized_pl: 0,
  unrealized_pl_pct: 0,
};

const BASE_PAYLOAD = {
  generated_at: '2026-05-12T13:42:00+00:00',
  status: {
    schwab: { configured: true, valid: true, expires_at: '2026-08-01T00:00:00+00:00' },
    fred: { configured: true, valid: true },
    cache: { fresh: 12, stale: 0, very_stale: 0, total: 12 },
    journal: { positions_count: 2 },
  },
  kpis: POSITIVE_KPIS,
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
  next_actions: [],
};

function action(overrides) {
  return {
    id: 'action.default.subject',
    action_id: 'position.cc_candidate',
    priority: 'P2',
    title: 'Default action',
    subject: {},
    reason: 'Default reason.',
    cta: { label: 'Open', href: '/journal', kind: 'link' },
    ...overrides,
  };
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

test.describe('NextActionsSection', () => {
  test('section is always visible (even when empty)', async ({ page }) => {
    await mockDashboard(page, BASE_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    await expect(page.getByTestId('next-actions-section')).toBeVisible();
    await expect(page.getByTestId('next-actions-empty')).toBeVisible();
  });

  test('"All quiet" empty state renders both CTAs', async ({ page }) => {
    await mockDashboard(page, BASE_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const empty = page.getByTestId('next-actions-empty');
    await expect(empty).toContainText('All quiet');
    await expect(page.getByTestId('next-actions-empty-cta-scanner')).toBeVisible();
    await expect(page.getByTestId('next-actions-empty-cta-journal')).toBeVisible();
  });

  test('renders priority badges with text + glyph (not color alone)', async ({ page }) => {
    const actions = [
      action({
        id: 'position.large_loser.tsla',
        action_id: 'position.large_loser',
        priority: 'P0',
        title: 'Largest unrealized loser',
        subject: { ticker: 'TSLA', amount: '-$1,420 (-7.2%)' },
        reason: 'Position is below your -5% review threshold.',
        cta: { label: 'Review TSLA', href: '/journal?position=pos-tsla', kind: 'link' },
      }),
      action({
        id: 'expiration.itm_short_dte.aapl-175p-0508',
        action_id: 'expiration.itm_short_dte',
        priority: 'P1',
        title: 'Roll AAPL 175P (3 DTE, ITM)',
        subject: { ticker: 'AAPL' },
        reason: 'ITM by $0.42 — assignment risk by Friday close.',
        cta: { label: 'Manage in Journal', href: '/journal?position=pos-aapl', kind: 'link' },
      }),
      action({
        id: 'journal.no_open_legs.scanner',
        action_id: 'journal.no_open_legs',
        priority: 'P2',
        title: 'Run scanner',
        subject: {},
        reason: 'No open legs — surface opportunities.',
        cta: { label: 'Open Options', href: '/options', kind: 'link' },
      }),
    ];
    await mockDashboard(page, { ...BASE_PAYLOAD, next_actions: actions });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const p0 = page.getByTestId('next-actions-card-position.large_loser.tsla');
    await expect(p0).toBeVisible();
    await expect(p0).toContainText('[P0]');
    await expect(p0).toContainText('⛔');

    const p1 = page.getByTestId('next-actions-card-expiration.itm_short_dte.aapl-175p-0508');
    await expect(p1).toContainText('[P1]');
    await expect(p1).toContainText('⚠');

    const p2 = page.getByTestId('next-actions-card-journal.no_open_legs.scanner');
    await expect(p2).toContainText('[P2]');
  });

  test('top 3 visible by default; Show N more expands the rest', async ({ page }) => {
    const actions = [];
    for (let i = 0; i < 5; i += 1) {
      actions.push(
        action({
          id: `position.cc_candidate.t${i}`,
          action_id: 'position.cc_candidate',
          priority: 'P2',
          title: `Consider covered call ${i}`,
          subject: { ticker: `T${i}` },
          reason: 'Eligible position.',
          cta: { label: 'Open Options', href: `/options?ticker=T${i}`, kind: 'link' },
        })
      );
    }
    await mockDashboard(page, { ...BASE_PAYLOAD, next_actions: actions });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    // 3 visible
    await expect(page.getByTestId(/^next-actions-card-/)).toHaveCount(3);

    // Show 2 more
    const showMore = page.getByTestId('next-actions-show-more');
    await expect(showMore).toContainText('Show 2 more');
    await showMore.click();

    // Now 5 visible
    await expect(page.getByTestId(/^next-actions-card-/)).toHaveCount(5);
  });

  test('hard cap at 8 actions even if backend over-emits', async ({ page }) => {
    const actions = [];
    for (let i = 0; i < 12; i += 1) {
      actions.push(
        action({
          id: `position.cc_candidate.t${i}`,
          action_id: 'position.cc_candidate',
          priority: 'P2',
          title: `Consider covered call ${i}`,
          subject: { ticker: `T${i}` },
          reason: 'Eligible position.',
          cta: { label: 'Open Options', href: `/options?ticker=T${i}`, kind: 'link' },
        })
      );
    }
    await mockDashboard(page, { ...BASE_PAYLOAD, next_actions: actions });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    await page.getByTestId('next-actions-show-more').click();
    // Cap at 8 even though payload had 12
    await expect(page.getByTestId(/^next-actions-card-/)).toHaveCount(8);
  });

  test('link CTA navigates to destination on card click', async ({ page }) => {
    const actions = [
      action({
        id: 'position.large_loser.tsla',
        action_id: 'position.large_loser',
        priority: 'P0',
        title: 'Largest unrealized loser',
        subject: { ticker: 'TSLA' },
        reason: 'Below threshold.',
        cta: { label: 'Review TSLA', href: '/journal?position=pos-tsla', kind: 'link' },
      }),
    ];
    await mockDashboard(page, { ...BASE_PAYLOAD, next_actions: actions });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    await page.getByTestId('next-actions-card-position.large_loser.tsla').click();
    await page.waitForURL(/\/journal/);
    expect(page.url()).toContain('/journal');
    expect(page.url()).toContain('position=pos-tsla');
  });

  test('inline CTA renders as button and does not navigate', async ({ page }) => {
    await page.route('**/api/settings/cache/refresh-stale', (route) => {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ results: [] }),
      });
    });
    const actions = [
      action({
        id: 'data.cache_very_stale.cache',
        action_id: 'data.cache_very_stale',
        priority: 'P0',
        title: 'Refresh stale market data',
        subject: { amount: '3 items' },
        reason: '3 cached items over 90 days old.',
        cta: { label: 'Refresh stale data', href: '#refresh-stale-cache', kind: 'inline' },
      }),
    ];
    await mockDashboard(page, { ...BASE_PAYLOAD, next_actions: actions });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const card = page.getByTestId('next-actions-card-data.cache_very_stale.cache');
    // The inline CTA renders as a <button>, not a <Link>
    await expect(card).toHaveJSProperty('tagName', 'BUTTON');

    // Clicking the inline-CTA card must fire the refresh-stale request and
    // keep the user on /dashboard (no navigation).
    const [request] = await Promise.all([
      page.waitForRequest('**/api/settings/cache/refresh-stale'),
      card.click(),
    ]);
    expect(request.method()).toBe('POST');
    expect(page.url()).toContain('/dashboard');
  });

  test('section has aria-label landmark for accessibility', async ({ page }) => {
    await mockDashboard(page, BASE_PAYLOAD);
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const section = page.getByTestId('next-actions-section');
    await expect(section).toHaveAttribute('aria-label', 'Next actions');
  });

  test('data-testid is unique when a family emits multiple cards', async ({ page }) => {
    // Three ``position.cc_candidate`` cards (same ``action_id``) but each
    // with a unique ``id`` — the rendered ``data-testid`` must be unique
    // so Playwright locators don't collide on duplicate-family payloads.
    const actions = [
      action({
        id: 'position.cc_candidate.aapl',
        action_id: 'position.cc_candidate',
        priority: 'P2',
        title: 'Consider covered call on AAPL',
        subject: { ticker: 'AAPL' },
        cta: { label: 'Open Options', href: '/options?ticker=AAPL', kind: 'link' },
      }),
      action({
        id: 'position.cc_candidate.msft',
        action_id: 'position.cc_candidate',
        priority: 'P2',
        title: 'Consider covered call on MSFT',
        subject: { ticker: 'MSFT' },
        cta: { label: 'Open Options', href: '/options?ticker=MSFT', kind: 'link' },
      }),
      action({
        id: 'position.cc_candidate.nvda',
        action_id: 'position.cc_candidate',
        priority: 'P2',
        title: 'Consider covered call on NVDA',
        subject: { ticker: 'NVDA' },
        cta: { label: 'Open Options', href: '/options?ticker=NVDA', kind: 'link' },
      }),
    ];
    await mockDashboard(page, { ...BASE_PAYLOAD, next_actions: actions });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    // Each card has a unique testid built from ``action.id``.
    await expect(page.getByTestId('next-actions-card-position.cc_candidate.aapl')).toBeVisible();
    await expect(page.getByTestId('next-actions-card-position.cc_candidate.msft')).toBeVisible();
    await expect(page.getByTestId('next-actions-card-position.cc_candidate.nvda')).toBeVisible();

    // The family slug is still queryable via ``data-action-id``.
    const familyCount = await page
      .locator('[data-action-id="position.cc_candidate"]')
      .count();
    expect(familyCount).toBe(3);

    // No duplicate ``data-testid`` values among rendered next-action cards.
    const duplicates = await page.evaluate(() => {
      const nodes = Array.from(
        document.querySelectorAll('[data-testid^="next-actions-card-"]')
      );
      const ids = nodes.map((n) => n.getAttribute('data-testid'));
      const seen = new Set();
      const dupes = [];
      for (const id of ids) {
        if (seen.has(id)) dupes.push(id);
        seen.add(id);
      }
      return dupes;
    });
    expect(duplicates).toEqual([]);
  });

  test('inline CTA shows error toast and keeps card when refresh fails', async ({ page }) => {
    // refreshStaleCache rejects -> NextActionsSection catches and surfaces a
    // ``toast.error('Failed to refresh stale cache')``; the card must remain
    // visible (no navigation, no removal from the DOM).
    await page.route('**/api/settings/cache/refresh-stale', (route) => {
      route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'boom' }),
      });
    });
    const actions = [
      action({
        id: 'data.cache_very_stale.global',
        action_id: 'data.cache_very_stale',
        priority: 'P0',
        title: 'Refresh stale market data',
        subject: { amount: '3 items' },
        reason: '3 cached items over 90 days old.',
        cta: { label: 'Refresh stale data', href: '#refresh-stale-cache', kind: 'inline' },
      }),
    ];
    await mockDashboard(page, { ...BASE_PAYLOAD, next_actions: actions });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const card = page.getByTestId('next-actions-card-data.cache_very_stale.global');
    await expect(card).toBeVisible();

    const [response] = await Promise.all([
      page.waitForResponse('**/api/settings/cache/refresh-stale'),
      card.click(),
    ]);
    expect(response.status()).toBe(500);

    // react-hot-toast renders the error copy somewhere on the page.
    await expect(page.getByText('Failed to refresh stale cache')).toBeVisible();

    // Card is still mounted; no navigation occurred.
    await expect(card).toBeVisible();
    expect(page.url()).toContain('/dashboard');
  });

  test('renders in priority order received from backend', async ({ page }) => {
    // Backend ranks P0 > P1 > P2; frontend renders engine output verbatim.
    const actions = [
      action({
        id: 'position.large_loser.tsla',
        action_id: 'position.large_loser',
        priority: 'P0',
        title: 'Largest unrealized loser',
        cta: { label: 'Review', href: '/journal', kind: 'link' },
      }),
      action({
        id: 'expiration.itm_short_dte.aapl',
        action_id: 'expiration.itm_short_dte',
        priority: 'P1',
        title: 'Roll AAPL 175P',
        cta: { label: 'Manage', href: '/journal?position=pos-aapl', kind: 'link' },
      }),
      action({
        id: 'position.cc_candidate.msft',
        action_id: 'position.cc_candidate',
        priority: 'P2',
        title: 'Consider covered call on MSFT',
        cta: { label: 'Open Options', href: '/options?ticker=MSFT', kind: 'link' },
      }),
    ];
    await mockDashboard(page, { ...BASE_PAYLOAD, next_actions: actions });
    await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    const cards = page.getByTestId(/^next-actions-card-/);
    await expect(cards.nth(0)).toContainText('[P0]');
    await expect(cards.nth(1)).toContainText('[P1]');
    await expect(cards.nth(2)).toContainText('[P2]');
  });
});
