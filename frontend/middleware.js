import { NextResponse } from "next/server";

/**
 * Auth is opt-in: middleware only enforces authentication when all three
 * OAuth env vars are configured (NEXTAUTH_SECRET, GITHUB_ID, GITHUB_SECRET).
 * When unconfigured or partially configured, all routes are public.
 */

const authSecret = process.env.NEXTAUTH_SECRET;
const githubId = process.env.GITHUB_ID;
const githubSecret = process.env.GITHUB_SECRET;

const authFullyConfigured = Boolean(authSecret && githubId && githubSecret);

const isPartiallyConfigured =
  !authFullyConfigured && Boolean(authSecret || githubId || githubSecret);

if (isPartiallyConfigured) {
  console.warn(
    "Auth partially configured — all three env vars (NEXTAUTH_SECRET, GITHUB_ID, GITHUB_SECRET) " +
      "are required to enable authentication. Running without auth.",
  );
}

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
