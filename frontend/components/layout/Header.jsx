'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useTheme } from '../../context/ThemeContext';
import UserMenu from './UserMenu';

export default function Header({ sessions, onLoadSession }) {
  const { dark, toggle } = useTheme();
  const pathname = usePathname();

  // Active-nav highlighting (issue #327 §5). Idle = today's link recipe
  // verbatim (zero visual change for an inactive link); active = the same
  // `bg-blue-600 text-white` token the Settings tab bar already uses, so an
  // "active nav item" reads consistently app-wide. `startsWith(href + '/')`
  // keeps nested routes lit; matching exact `/dashboard` etc. avoids a bare
  // `/` false positive against other routes.
  const isActive = (href) => pathname === href || pathname?.startsWith(href + '/');
  const navClass = (href) =>
    `shrink-0 px-3 py-1.5 rounded-lg text-sm font-medium ${
      isActive(href)
        ? 'bg-blue-600 text-white'
        : 'text-slate-600 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-700'
    }`;

  return (
    <header className="h-14 border-b border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 flex items-center justify-between px-4 shrink-0">
      <Link href="/dashboard" className="shrink-0 text-lg font-semibold text-slate-900 dark:text-white hover:text-blue-600 dark:hover:text-blue-400">
        Regression Analysis Tool
      </Link>

      <div className="flex items-center gap-3 overflow-x-auto">
        <UserMenu />
        {/* Dashboard link — default landing route per #114 */}
        <Link
          href="/dashboard"
          className={navClass('/dashboard')}
          aria-current={isActive('/dashboard') ? 'page' : undefined}
        >
          Dashboard
        </Link>
        {/* Analysis link — moved from `/` to `/analysis` per #114 */}
        <Link
          href="/analysis"
          className={navClass('/analysis')}
          aria-current={isActive('/analysis') ? 'page' : undefined}
        >
          Analysis
        </Link>
        {/* Options scanner link */}
        <Link
          href="/options"
          className={navClass('/options')}
          aria-current={isActive('/options') ? 'page' : undefined}
        >
          Options
        </Link>

        {/* Watchlist link — the approved-universe gate, promoted to top-level
            (issue #327). Placed between Options and Journal, left-adjacent to
            the scanner it gates; Journal stays rightmost as the post-trade
            record (spec §3.3). */}
        <Link
          href="/watchlist"
          data-testid="nav-watchlist-link"
          className={navClass('/watchlist')}
          aria-current={isActive('/watchlist') ? 'page' : undefined}
        >
          Watchlist
        </Link>

        {/* Journal link */}
        <Link
          href="/journal"
          className={navClass('/journal')}
          aria-current={isActive('/journal') ? 'page' : undefined}
        >
          Journal
        </Link>

        {/* Saved sessions dropdown */}
        {sessions.length > 0 && (
          <select
            onChange={(e) => e.target.value && onLoadSession(e.target.value)}
            defaultValue=""
            className="shrink-0 text-sm border border-slate-300 dark:border-slate-600 rounded px-2 py-1 bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100"
          >
            <option value="">Saved Sessions</option>
            {sessions.map((s) => (
              <option key={s.id} value={s.id}>{s.name}</option>
            ))}
          </select>
        )}

        {/* Settings link */}
        <Link
          href="/settings"
          className="shrink-0 p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300"
          aria-label="Settings"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
        </Link>

        {/* Help link */}
        <Link
          href="/help"
          className="shrink-0 p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300"
          aria-label="Help"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
        </Link>

        {/* Dark mode toggle */}
        <button
          data-testid="dark-mode-toggle"
          onClick={toggle}
          className="shrink-0 p-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300"
          aria-label="Toggle dark mode"
        >
          {dark ? (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
            </svg>
          ) : (
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
            </svg>
          )}
        </button>
      </div>
    </header>
  );
}
