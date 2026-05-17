import { NextResponse } from "next/server";

/**
 * Auth is opt-in: middleware enforces authentication when NEXTAUTH_SECRET is
 * set. This aligns with the backend, which also checks only NEXTAUTH_SECRET.
 * GITHUB_ID and GITHUB_SECRET are still required by NextAuth's OAuth provider
 * but are not checked here — the middleware guard fires on NEXTAUTH_SECRET alone.
 * When NEXTAUTH_SECRET is absent, all routes are public.
 *
 * Issue #114: authenticated users hitting `/` are redirected to `/dashboard`
 * (the new default landing route). When auth is *not* configured, the
 * `app/page.jsx` server-side redirect handles the same case so unauthenticated
 * deployments still land on the dashboard. Belt and suspenders.
 *
 * Issue #33: nonce-based Content-Security-Policy. A fresh per-request nonce is
 * generated here (the only layer that renders the HTML) and:
 *   - set on the *request* headers (`x-nonce` + `Content-Security-Policy`) so
 *     Next.js 16 stamps the same nonce onto every framework/runtime inline
 *     `<script>` at render time;
 *   - set on the *response* headers so the browser enforces the policy.
 * Both are required: the request header drives render-time propagation, the
 * response header drives browser enforcement. Caddy no longer sets CSP for app
 * routes (see deploy/Caddyfile) so this middleware is the single source of
 * truth for the `script-src` policy. Gated by `CSP_NONCE_ENABLED` (default on)
 * as a no-redeploy kill-switch — when off, no CSP header is emitted and a
 * Caddy-restored static header can take over.
 */

const authSecret = process.env.NEXTAUTH_SECRET;

const authFullyConfigured = Boolean(authSecret);

// Kill-switch: any value other than an explicit "false" leaves nonce CSP on.
const cspNonceEnabled = process.env.CSP_NONCE_ENABLED !== "false";

/**
 * Build the Content-Security-Policy header value for a given nonce.
 *
 * `script-src` carries `'nonce-<value>'` (replacing the old `'unsafe-inline'`)
 * plus `'wasm-unsafe-eval'` — the latter is required by `plotly.js-finance-dist`
 * (WebAssembly) and must not be dropped or charts break. `style-src` keeps
 * `'unsafe-inline'` intentionally: Next.js + Tailwind v4 inject inline styles
 * and Next.js does not nonce inline styles; issue #33 scopes the hardening to
 * `script-src` only.
 *
 * @param {string} nonce - The per-request base64 nonce.
 * @returns {string} The CSP header value.
 */
function buildContentSecurityPolicy(nonce) {
  return [
    "default-src 'self'",
    `script-src 'self' 'nonce-${nonce}' 'wasm-unsafe-eval'`,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: https:",
    "font-src 'self' data:",
    "connect-src 'self'",
  ].join("; ");
}

/**
 * Generate a fresh per-request CSP nonce.
 *
 * Uses the Edge-runtime Web Crypto global (`crypto.getRandomValues`) — Node's
 * `crypto` module must not be imported here, it fails the edge build. 16 random
 * bytes give 128 bits of entropy, matching the CSP-spec recommendation.
 *
 * @returns {string} A base64-encoded nonce.
 */
function generateNonce() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  return btoa(String.fromCharCode(...bytes));
}

async function middleware(request) {
  // When the kill-switch is off, bypass all nonce/CSP plumbing entirely.
  if (!cspNonceEnabled) {
    if (!authFullyConfigured) {
      return NextResponse.next();
    }
    const { auth } = await import("@/auth");
    const wrapped = auth((req) => {
      if (!req.auth?.user) {
        const signInUrl = new URL("/auth/signin", req.url);
        signInUrl.searchParams.set("callbackUrl", req.url);
        return NextResponse.redirect(signInUrl);
      }
      if (
        req.nextUrl.pathname === "/" &&
        !req.nextUrl.searchParams.get("session")
      ) {
        return NextResponse.redirect(new URL("/dashboard", req.url));
      }
      return NextResponse.next();
    });
    return wrapped(request);
  }

  const nonce = generateNonce();
  const csp = buildContentSecurityPolicy(nonce);

  // Clone the incoming request headers and stamp the nonce + CSP onto them.
  // Passing these through `NextResponse.next({ request })` is what makes
  // Next.js see the policy at render time and propagate the nonce to its
  // framework inline scripts.
  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("x-nonce", nonce);
  requestHeaders.set("Content-Security-Policy", csp);

  /**
   * Attach the CSP response header to any NextResponse before returning it.
   * @param {import("next/server").NextResponse} response
   * @returns {import("next/server").NextResponse}
   */
  const withCsp = (response) => {
    response.headers.set("Content-Security-Policy", csp);
    return response;
  };

  if (!authFullyConfigured) {
    // No auth configured: let the static `app/page.jsx` redirect handle `/`.
    return withCsp(NextResponse.next({ request: { headers: requestHeaders } }));
  }

  // Use the Auth.js middleware wrapper pattern — await auth() without a
  // request argument cannot read cookies in middleware context. Every
  // NextResponse the callback builds threads `requestHeaders` so the nonce
  // reaches render regardless of how the auth() wrapper forwards the request,
  // and `withCsp` stamps the enforced response header on the final value.
  const { auth } = await import("@/auth");
  const wrapped = auth((req) => {
    if (!req.auth?.user) {
      const signInUrl = new URL("/auth/signin", req.url);
      signInUrl.searchParams.set("callbackUrl", req.url);
      return withCsp(NextResponse.redirect(signInUrl));
    }
    // Authenticated: redirect bare `/` to `/dashboard`. Preserve any
    // `?session=` param by deferring to the static page.jsx fallback when it's
    // present (the session-recovery URL form pre-#114).
    if (
      req.nextUrl.pathname === "/" &&
      !req.nextUrl.searchParams.get("session")
    ) {
      return withCsp(NextResponse.redirect(new URL("/dashboard", req.url)));
    }
    return withCsp(
      NextResponse.next({ request: { headers: requestHeaders } }),
    );
  });

  return wrapped(request);
}

export { middleware };

export const config = {
  matcher: [
    // Protect all routes except:
    // - /auth/* (sign-in pages)
    // - /api/auth/* (NextAuth API routes)
    // - /_next/* (Next.js internals)
    // - /favicon.ico, /public assets
    "/((?!auth|api/auth|_next/static|_next/image|favicon\\.ico).*)",
  ],
};
