import { test, expect } from '@playwright/test';

/**
 * Issue #229 — production regression guard for the nonce-based CSP (#33).
 *
 * The v1.0.0 release shipped nonce-based CSP (`frontend/middleware.js`, #33). It
 * broke production: `/dashboard` was statically prerendered at build time, so
 * its inline framework `<script>` tags carried no nonce — while the middleware
 * still emits a fresh per-request `script-src 'nonce-…'` CSP on every response.
 * The browser blocked the nonce-less inline `__next_f` hydration scripts, React
 * never hydrated, and the page hung forever on its loading skeleton.
 *
 * `csp-nonce.spec.js` could not catch this: it runs against `next dev`, which
 * never statically prerenders, so its inline-script nonce check always passed.
 * This suite runs against a *production build* (`next build && next start`, see
 * `playwright.prod.config.js`) — the only environment where the bug reproduces.
 * Run pre-fix, the second and third tests below FAIL.
 *
 * The fix (`app/layout.jsx`) sets `export const dynamic = 'force-dynamic'`,
 * which forces every route to render per-request so the middleware nonce
 * reaches Next.js at render time and is stamped onto the inline scripts.
 *
 * Run: `npm run test:e2e:prod`.
 *
 * Auth-aware (mirrors `csp-nonce.spec.js`): with `NEXTAUTH_SECRET` set when the
 * server starts, `/dashboard` 307s to `/auth/signin` (matcher-excluded) and the
 * rendered-page assertions skip with a documented reason. The full suite runs
 * when auth is off (the CI default).
 */

/**
 * Extract the `script-src` directive substring from a CSP header value.
 * @param {string | undefined} csp - The raw Content-Security-Policy header.
 * @returns {string} The `script-src` directive, or '' if absent.
 */
function scriptSrcDirective(csp) {
  if (!csp) return '';
  const directive = csp
    .split(';')
    .map((part) => part.trim())
    .find((part) => part.startsWith('script-src'));
  return directive ?? '';
}

/**
 * Parse the nonce value out of a CSP header's `script-src` directive.
 * @param {string | undefined} csp - The raw Content-Security-Policy header.
 * @returns {string | null} The nonce, or null if no nonce token is present.
 */
function parseNonce(csp) {
  const match = scriptSrcDirective(csp).match(/'nonce-([A-Za-z0-9+/=]+)'/);
  return match ? match[1] : null;
}

/**
 * Fetch `/dashboard` without following redirects, so the captured response is
 * the one the Next.js middleware produced for this request.
 * @param {import('@playwright/test').APIRequestContext} request
 * @returns {Promise<import('@playwright/test').APIResponse>}
 */
function fetchDashboard(request) {
  return request.get('/dashboard', { maxRedirects: 0 });
}

test.describe('Nonce CSP — production build (#229)', () => {
  test('/dashboard is rendered dynamically, not statically prerendered', async ({
    request,
  }) => {
    const response = await fetchDashboard(request);
    test.skip(
      response.status() >= 300 && response.status() < 400,
      'Auth enforced — /dashboard redirects; dynamic-render check needs a rendered page',
    );

    expect(response.status()).toBe(200);
    // A statically prerendered route is served with the `x-nextjs-prerender`
    // header. `force-dynamic` (app/layout.jsx) renders the route per-request
    // instead — which is what lets the middleware's per-request nonce reach
    // render. If this header reappears, the #229 outage is back.
    expect(
      response.headers()['x-nextjs-prerender'],
      '/dashboard must not be statically prerendered (issue #229)',
    ).toBeUndefined();
  });

  test('inline framework scripts carry the per-request nonce in production HTML', async ({
    request,
  }) => {
    const response = await fetchDashboard(request);
    test.skip(
      response.status() >= 300 && response.status() < 400,
      'Auth enforced — /dashboard redirects; inline-script check needs a rendered page',
    );

    const headerNonce = parseNonce(
      response.headers()['content-security-policy'],
    );
    expect(headerNonce, 'response CSP carries a nonce').toBeTruthy();

    // Assert against the raw server-emitted HTML. On the pre-fix production
    // build, `/dashboard` is prerendered and its inline `__next_f` scripts have
    // no nonce attribute at all — so `nonceAttrs` is empty and this fails.
    const html = await response.text();
    const nonceAttrs = [
      ...html.matchAll(/<script[^>]*\snonce="([A-Za-z0-9+/=]+)"/gi),
    ].map((m) => m[1]);

    expect(
      nonceAttrs.length,
      'at least one inline <script> in the production HTML carries a nonce',
    ).toBeGreaterThan(0);
    // Every nonce Next.js stamped must equal the one in the response header,
    // or the browser blocks the script.
    for (const attr of nonceAttrs) {
      expect(
        attr,
        'each inline script nonce matches the response CSP nonce',
      ).toBe(headerNonce);
    }
  });

  test('the dashboard hydrates under the nonce CSP with no script-src violations', async ({
    page,
    request,
  }) => {
    const probe = await fetchDashboard(request);
    test.skip(
      probe.status() >= 300 && probe.status() < 400,
      'Auth enforced — /dashboard redirects; hydration covered when auth is off',
    );

    const cspViolations = [];
    page.on('console', (msg) => {
      const text = msg.text();
      if (/content security policy/i.test(text) && /script/i.test(text)) {
        cspViolations.push(text);
      }
    });

    await page.goto('/dashboard');

    // The dark-mode toggle lives inside the client-only DashboardPage. A
    // working toggle proves React hydrated — i.e. the inline framework scripts
    // executed under the nonce CSP. Pre-fix, those scripts were blocked, the
    // client bundle never booted, and the toggle never appeared.
    const toggle = page.getByTestId('dark-mode-toggle');
    await expect(toggle).toBeVisible({ timeout: 15000 });

    const html = page.locator('html');
    const hadDark = await html.evaluate((el) => el.classList.contains('dark'));
    await toggle.click();
    if (hadDark) {
      await expect(html).not.toHaveClass(/(?:^|\s)dark(?:\s|$)/);
    } else {
      await expect(html).toHaveClass(/(?:^|\s)dark(?:\s|$)/);
    }

    expect(
      cspViolations,
      `no script-src CSP violations: ${cspViolations.join(' | ')}`,
    ).toHaveLength(0);
  });
});
