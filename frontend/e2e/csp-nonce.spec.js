import { test, expect } from '@playwright/test';

/**
 * Issue #33 — nonce-based Content-Security-Policy for `script-src`.
 *
 * PR #32 had added `'unsafe-inline'` to `script-src` to unblock Next.js
 * hydration, which weakens XSS protection. This change moves CSP generation
 * into `frontend/middleware.js`, which mints a fresh per-request nonce and
 * emits `script-src 'nonce-<value>' 'wasm-unsafe-eval'` (no `'unsafe-inline'`).
 *
 * These tests run against the Playwright `webServer` (`npm run dev`) — Caddy is
 * NOT in the loop. That is intentional: the nonce must originate from the
 * Next.js middleware (the only layer rendering the HTML), so `next dev`
 * exercises the real production code path and is the source of truth.
 *
 * Auth-aware: like `auth-flow.spec.js`, behavior depends on whether
 * `NEXTAUTH_SECRET` is set when the dev server starts.
 *   - Auth NOT configured (CI default — routes public): `/dashboard` renders,
 *     so the full suite runs, including the hydration / inline-script checks.
 *   - Auth configured (e.g. a local `.env.local`): protected routes 307 to
 *     `/auth/signin`, which is excluded from the middleware matcher. The CSP
 *     header is still asserted on the middleware-issued redirect response
 *     (the middleware stamps CSP on redirects too), and the hydration checks
 *     are skipped with a documented reason — the redirect chain leaves the
 *     dev server and the rendered page is not under this middleware's control.
 *
 * Non-automatable AC — the `deploy/Caddyfile` edit (removing the static CSP
 * line so it no longer shadows the middleware header) cannot be exercised here
 * because e2e runs against `next dev`, not Caddy. It is verified manually on
 * deploy. These tests cover the Next.js side, which is what produces the nonce.
 *
 * Scope note — `style-src 'unsafe-inline'` is intentionally retained: Next.js
 * + Tailwind v4 inject inline styles and Next.js does not nonce inline styles.
 * Issue #33 scopes the hardening to `script-src` only; this is not an oversight.
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
 * Parse the nonce value out of a `script-src` directive.
 * @param {string} csp - The raw Content-Security-Policy header.
 * @returns {string | null} The nonce, or null if no nonce token is present.
 */
function parseNonce(csp) {
  const match = scriptSrcDirective(csp).match(/'nonce-([A-Za-z0-9+/=]+)'/);
  return match ? match[1] : null;
}

/**
 * Assert a CSP header value satisfies issue #33: a nonce token is present,
 * `'unsafe-inline'` is gone from `script-src`, and `'wasm-unsafe-eval'` stays.
 * @param {string | undefined} csp - The raw Content-Security-Policy header.
 */
function assertNonceCsp(csp) {
  expect(csp, 'a Content-Security-Policy header is present').toBeTruthy();
  const scriptSrc = scriptSrcDirective(csp);
  expect(scriptSrc, 'script-src directive is present').not.toBe('');
  // A per-request nonce token must be present.
  expect(scriptSrc).toMatch(/'nonce-[A-Za-z0-9+/=]+'/);
  // 'unsafe-inline' must no longer be granted to scripts — the core AC of #33.
  expect(scriptSrc).not.toContain("'unsafe-inline'");
  // 'wasm-unsafe-eval' must be retained — plotly.js-finance-dist uses WASM.
  expect(scriptSrc).toContain("'wasm-unsafe-eval'");
}

/**
 * Fetch `/dashboard` without following redirects so the response captured is
 * the one the Next.js middleware produced for this request.
 * @param {import('@playwright/test').APIRequestContext} request
 * @returns {Promise<import('@playwright/test').APIResponse>}
 */
function fetchDashboard(request, suffix = '') {
  return request.get(`/dashboard${suffix}`, { maxRedirects: 0 });
}

test.describe('Nonce-based CSP (#33)', () => {
  test('script-src uses a nonce, drops unsafe-inline, keeps wasm-unsafe-eval', async ({
    request,
  }) => {
    // maxRedirects: 0 — capture the exact response the middleware emitted,
    // whether that is the rendered page (auth off) or a redirect (auth on).
    // The middleware stamps the nonce CSP on both.
    const response = await fetchDashboard(request);
    assertNonceCsp(response.headers()['content-security-policy']);
  });

  test('nonce is fresh per request (not reused or cached)', async ({
    request,
  }) => {
    const first = await fetchDashboard(request);
    const second = await fetchDashboard(request, '?cb=1');

    const firstNonce = parseNonce(
      first.headers()['content-security-policy'],
    );
    const secondNonce = parseNonce(
      second.headers()['content-security-policy'],
    );

    expect(firstNonce, 'first response carries a nonce').toBeTruthy();
    expect(secondNonce, 'second response carries a nonce').toBeTruthy();
    expect(
      firstNonce,
      'each request gets a distinct nonce',
    ).not.toBe(secondNonce);
  });

  test('app hydrates under the nonce CSP with no script-src violations', async ({
    page,
    request,
  }) => {
    // Hydration can only be exercised when the dashboard renders directly.
    // With auth configured the route 307s to /auth/signin (matcher-excluded),
    // so the rendered page is not produced by this middleware — skip cleanly.
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

    const response = await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');
    assertNonceCsp(response.headers()['content-security-policy']);

    // The dark-mode toggle is a client component — a working toggle proves
    // React hydrated, i.e. the framework inline scripts executed under the
    // nonce. If the nonce were missing/mismatched, hydration would be blocked.
    const toggle = page.getByTestId('dark-mode-toggle');
    await expect(toggle).toBeVisible();

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

  test('inline framework scripts carry the matching nonce in the HTML', async ({
    request,
  }) => {
    // Inline framework scripts only exist on a rendered page — see the skip
    // rationale in the hydration test above.
    const response = await fetchDashboard(request);
    test.skip(
      response.status() >= 300 && response.status() < 400,
      'Auth enforced — /dashboard redirects; inline-script check needs a rendered page',
    );

    const headerNonce = parseNonce(
      response.headers()['content-security-policy'],
    );
    expect(headerNonce, 'response CSP carries a nonce').toBeTruthy();

    // Verify against the *raw HTML body* the server emitted, not the live DOM.
    // Modern browsers blank out the `nonce` DOM attribute AND property after
    // parsing (an anti-exfiltration measure), so `getAttribute('nonce')`
    // returns '' in page context — the nonce is still honoured during parse,
    // which is why scripts execute and the page hydrates. The server-rendered
    // HTML is where Next.js stamps the nonce, so assert it there.
    const html = await response.text();
    const nonceAttrs = [
      ...html.matchAll(/<script[^>]*\snonce="([A-Za-z0-9+/=]+)"/gi),
    ].map((m) => m[1]);

    expect(
      nonceAttrs.length,
      'at least one inline <script> in the HTML carries a nonce attribute',
    ).toBeGreaterThan(0);
    // Every nonce Next.js stamped must equal the one in the response header.
    for (const attr of nonceAttrs) {
      expect(
        attr,
        'each framework script nonce matches the response CSP nonce',
      ).toBe(headerNonce);
    }
  });
});
