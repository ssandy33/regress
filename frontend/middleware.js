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
 */

const authSecret = process.env.NEXTAUTH_SECRET;

const authFullyConfigured = Boolean(authSecret);

async function middleware(request) {
  if (!authFullyConfigured) {
    // No auth configured: let the static `app/page.jsx` redirect handle `/`.
    return NextResponse.next();
  }

  // Use the Auth.js middleware wrapper pattern — await auth() without a
  // request argument cannot read cookies in middleware context.
  const { auth } = await import("@/auth");
  const wrapped = auth((req) => {
    if (!req.auth?.user) {
      const signInUrl = new URL("/auth/signin", req.url);
      signInUrl.searchParams.set("callbackUrl", req.url);
      return NextResponse.redirect(signInUrl);
    }
    // Authenticated: redirect bare `/` to `/dashboard`. Preserve any
    // `?session=` param by deferring to the static page.jsx fallback when it's
    // present (the session-recovery URL form pre-#114).
    if (req.nextUrl.pathname === "/" && !req.nextUrl.searchParams.get("session")) {
      return NextResponse.redirect(new URL("/dashboard", req.url));
    }
    return NextResponse.next();
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
