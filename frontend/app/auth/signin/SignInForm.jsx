"use client";

import { signIn } from "next-auth/react";
import { useSearchParams } from "next/navigation";

/**
 * Client-side sign-in form. Renders the GitHub OAuth button only when the
 * provider is configured; otherwise shows a self-explanatory not-configured
 * message instead of a button that would hand off to GitHub with an empty
 * client_id and fail into a GitHub 404 (issue #335).
 *
 * `githubConfigured` is computed server-side in the page wrapper (it reads
 * GITHUB_ID/GITHUB_SECRET, which are server-only env vars) and passed down as
 * a non-secret boolean.
 */
export default function SignInForm({ githubConfigured }) {
  const searchParams = useSearchParams();
  const callbackUrl = searchParams.get("callbackUrl") || "/";

  if (!githubConfigured) {
    return (
      <div
        className="mt-8 rounded-lg border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20 p-4 text-center"
        data-testid="github-not-configured"
      >
        <p className="text-sm font-medium text-amber-800 dark:text-amber-200">
          GitHub OAuth is not configured for this environment
        </p>
        <p className="mt-1 text-xs text-amber-700 dark:text-amber-300">
          Set GITHUB_ID and GITHUB_SECRET to enable sign-in.
        </p>
      </div>
    );
  }

  return (
    <div className="mt-8 space-y-4">
      <button
        onClick={() => signIn("github", { callbackUrl })}
        className="w-full flex items-center justify-center gap-3 px-4 py-3 border border-gray-300 dark:border-gray-600 rounded-lg shadow-sm bg-white dark:bg-gray-800 text-gray-700 dark:text-gray-200 hover:bg-gray-50 dark:hover:bg-gray-700 transition-colors"
      >
        <svg className="w-5 h-5" viewBox="0 0 24 24" fill="currentColor">
          <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z" />
        </svg>
        Sign in with GitHub
      </button>
    </div>
  );
}
