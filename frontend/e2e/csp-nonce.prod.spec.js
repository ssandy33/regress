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
 * rendered-page assertions skip with a documented reason. Run with auth off
 * (`NEXTAUTH_SECRET` unset) to exercise the full suite — CI does not run this
 * suite today (see issue #231 to wire it in).
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

/**
 * Issue #405 — no `script-src` eval violation on the production dashboard.
 *
 * The report: Chrome DevTools' *Issues* panel flags a `Content-Security-Policy`
 * violation on the prod `/dashboard` — `script-src` blocking a string-eval
 * (`eval()` / `new Function()`). The subtlety is that a *caught* eval probe —
 * e.g. a bundled `globalThis` polyfill's `Function("return this")()` fallback,
 * or zod v4's `allowsEval` check — still fires the `securitypolicyviolation`
 * DOM event *before* the exception is swallowed. The hydration tests (here and
 * in `csp-nonce.spec.js`) listen on `page.on('console')`, which sees thrown /
 * logged CSP errors but NOT a silently-caught probe — so neither catches this
 * class of violation.
 *
 * This test lives in the *production-build* suite deliberately. It cannot go in
 * `csp-nonce.spec.js`: that runs against `next dev`, whose
 * `react-server-dom-turbopack` **development** runtime legitimately uses `eval`
 * (hot-reload / flight protocol), firing `securitypolicyviolation` events that
 * never exist in a production build. Only `next build && next start` (this
 * config) reproduces what prod actually serves — the same reasoning that put
 * the #229 guard here rather than in the dev suite.
 *
 * On current `main` this passes: a headless-Chromium load of the production
 * `/dashboard` under the live `script-src 'self' 'nonce-…' 'wasm-unsafe-eval'`
 * policy (no `'unsafe-eval'`) fires **zero** eval violations. The only
 * `Function("return this")()` in the browser chunks is short-circuited by a
 * `typeof globalThis === 'object'` guard and never executes in a modern
 * browser; zod is a Node-only build-time dependency that never reaches the
 * bundle. The reported symptom traced to a stale prod image predating the
 * current Turbopack chunk isolation (Hypothesis C in the issue). This test is
 * the behavioral regression guard — it goes red if any future change (or a
 * stale deploy) reintroduces a runtime eval the policy blocks on the dashboard,
 * and it does so WITHOUT adding `'unsafe-eval'` (the wrong fix, per the AC).
 *
 * Run: `npm run test:e2e:prod`. (CI does not run the prod suite yet — issue
 * #231.)
 */
test.describe('Dashboard eval-probe CSP regression — production build (#405)', () => {
  test('no script-src eval securitypolicyviolation fires on the production /dashboard', async ({
    page,
    request,
  }) => {
    // The securitypolicyviolation event only fires on a rendered page. With
    // auth configured `/dashboard` 307s to /auth/signin (matcher-excluded), so
    // there is no page to observe — skip cleanly, matching the tests above.
    const probe = await fetchDashboard(request);
    test.skip(
      probe.status() >= 300 && probe.status() < 400,
      'Auth enforced — /dashboard redirects; eval-probe check needs a rendered page',
    );

    // Register the listener before any page script runs (addInitScript) so a
    // probe firing during early module evaluation is captured. Collect into a
    // page-context array and read it back after load — more robust than parsing
    // console text.
    await page.addInitScript(() => {
      window.__cspViolations = [];
      document.addEventListener('securitypolicyviolation', (event) => {
        window.__cspViolations.push({
          violatedDirective: event.violatedDirective,
          blockedURI: event.blockedURI,
          sourceFile: event.sourceFile,
          lineNumber: event.lineNumber,
          sample: event.sample,
        });
      });
    });

    const response = await page.goto('/dashboard');
    await page.waitForLoadState('networkidle');

    // The nonce CSP must actually be in force — a missing policy would make a
    // "zero violations" result meaningless. Assert the exact prod directive.
    const scriptSrc = scriptSrcDirective(
      response.headers()['content-security-policy'],
    );
    expect(scriptSrc, 'script-src directive is present').not.toBe('');
    expect(scriptSrc, 'a per-request nonce is present').toMatch(
      /'nonce-[A-Za-z0-9+/=]+'/,
    );
    expect(
      scriptSrc,
      "the wrong fix — 'unsafe-eval' — must NOT be present (issue #405 AC)",
    ).not.toContain("'unsafe-eval'");

    // Give lazily-imported client chunks (e.g. plotly) a beat to evaluate — the
    // point at which a bundled eval probe would fire — before reading results.
    await page.waitForTimeout(2000);

    const violations = await page.evaluate(() => window.__cspViolations || []);
    // Scope to script-src / eval-family violations — the subject of #405.
    const evalViolations = violations.filter((v) =>
      /script-src|eval/i.test(`${v.violatedDirective} ${v.blockedURI}`),
    );

    expect(
      evalViolations,
      `no script-src eval CSP violations on /dashboard: ${JSON.stringify(
        evalViolations,
      )}`,
    ).toHaveLength(0);
  });
});
