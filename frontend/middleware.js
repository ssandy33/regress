import { NextResponse } from "next/server";

/**
 * Auth is opt-in: middleware enforces authentication when NEXTAUTH_SECRET is
 * set. This aligns with the backend, which also checks only NEXTAUTH_SECRET.
 * GITHUB_ID and GITHUB_SECRET are still required by NextAuth's OAuth provider
 * but are not checked here — the middleware guard fires on NEXTAUTH_SECRET alone.
 * When NEXTAUTH_SECRET is absent, all routes are public.
 */

const authSecret = process.env.NEXTAUTH_SECRET;

const authFullyConfigured = Boolean(authSecret);

async function middleware(request) {
  if (!authFullyConfigured) {
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
