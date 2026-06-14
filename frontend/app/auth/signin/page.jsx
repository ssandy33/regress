import { Suspense } from "react";

import SignInForm from "./SignInForm";

/**
 * Sign-in page (server component).
 *
 * Reads the server-only GITHUB_ID/GITHUB_SECRET env vars and passes a
 * non-secret `githubConfigured` boolean down to the client `SignInForm`.
 * When the provider is half-configured (NEXTAUTH_SECRET set but the GitHub
 * creds blank — the QA default), the form renders a self-explanatory
 * "not configured" message instead of a button that would 404 on GitHub
 * with an empty client_id (issue #335). The middleware enforcement gate,
 * which keys on NEXTAUTH_SECRET alone, is unchanged.
 */
export default function SignInPage() {
  const githubConfigured = Boolean(
    process.env.GITHUB_ID && process.env.GITHUB_SECRET,
  );

  return (
    <div className="min-h-screen flex items-center justify-center bg-gray-50 dark:bg-gray-900">
      <div className="max-w-md w-full space-y-8 p-8">
        <div className="text-center">
          <h1 className="text-3xl font-bold text-gray-900 dark:text-white">
            Regression Tool
          </h1>
          <p className="mt-2 text-sm text-gray-600 dark:text-gray-400">
            Financial regression analysis
          </p>
        </div>

        <Suspense>
          <SignInForm githubConfigured={githubConfigured} />
        </Suspense>

        <p className="text-center text-xs text-gray-500 dark:text-gray-500 mt-6">
          Access restricted to authorized users
        </p>
      </div>
    </div>
  );
}
