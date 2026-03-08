import { NextResponse } from "next/server";

/**
 * Auth is opt-in: middleware only enforces authentication when all three
 * OAuth env vars are configured (NEXTAUTH_SECRET, GITHUB_ID, GITHUB_SECRET).
 * When unconfigured or partially configured, all routes are public.
 */

const authSecret = process.env.AUTH_SECRET || process.env.NEXTAUTH_SECRET;
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

  // Dynamically import auth only when fully configured
  const { auth } = await import("@/auth");
  const session = await auth();

  if (!session?.user) {
    const signInUrl = new URL("/auth/signin", request.url);
    signInUrl.searchParams.set("callbackUrl", request.url);
    return NextResponse.redirect(signInUrl);
  }

  return NextResponse.next();
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
