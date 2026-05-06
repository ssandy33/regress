import { redirect } from 'next/navigation';

/**
 * Root route — redirects to the dashboard, the new default landing page.
 *
 * Per spec/plan §7.4: when a `?session=<id>` query is present (legacy URLs
 * for saved Analysis sessions), redirect to `/analysis?session=<id>` so the
 * session still loads. Everything else lands on `/dashboard`.
 *
 * This is a Server Component — `redirect()` from `next/navigation` works at
 * the server boundary. The middleware also performs an authenticated `/` →
 * `/dashboard` redirect; this page is a belt-and-suspenders fallback for
 * deployments where auth is not configured.
 */
export default async function RootPage({ searchParams }) {
  const params = (await searchParams) ?? {};
  const sessionParam = params.session;
  const sessionId = Array.isArray(sessionParam) ? sessionParam[0] : sessionParam;
  if (sessionId) {
    redirect(`/analysis?session=${encodeURIComponent(sessionId)}`);
  }
  redirect('/dashboard');
}
