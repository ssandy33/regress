import './globals.css';
import Providers from './providers';

export const metadata = {
  title: 'Regression Tool',
  description: 'Financial regression analysis tool',
};

/**
 * Force every route to render per-request (issue #229).
 *
 * `frontend/middleware.js` mints a fresh per-request CSP nonce and emits
 * `script-src 'nonce-…'` on every response. For that nonce to be honoured the
 * inline framework `<script>` tags must carry the *same* nonce — and Next.js
 * only stamps it onto them when the page is rendered per-request.
 *
 * Statically prerendered pages bake their HTML (and nonce-less inline scripts)
 * at build time, before the middleware exists. The browser then blocks those
 * inline scripts against the per-request nonce CSP, hydration never runs, and
 * the page hangs on its loading skeleton (the v1.0.0 production outage).
 *
 * Setting `force-dynamic` on the root layout cascades to all routes, so the
 * nonce always reaches render. This app is per-user and authenticated — it has
 * no meaningful static content, so opting out of static optimization costs
 * nothing. Do not remove this without also removing the nonce CSP.
 */
export const dynamic = 'force-dynamic';

export default function RootLayout({ children }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
