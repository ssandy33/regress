import { useState } from 'react';
import toast from 'react-hot-toast';
import Link from 'next/link';
import NextActionCard from './NextActionCard';
import { refreshStaleCache } from '../../api/client';

/**
 * NextActionsSection — the thesis section of the V0.5 dashboard.
 *
 * Renders the server-ranked ``next_actions`` array as priority-styled cards.
 * Always visible (including the empty-state "All quiet" surface). Per spec
 * §2.2 and #152 AC:
 *
 *   - Top 3 cards visible by default; ``[Show N more]`` expands the rest.
 *   - Hard cap at 8 total actions per render. Engine output beyond 8 is
 *     truncated client-side as a defensive measure (the backend already
 *     caps at 8 per ``action_engine.MAX_ACTIONS``).
 *   - Inline-CTA actions render as ``<button>`` and call
 *     ``refreshStaleCache()`` in place (currently only
 *     ``data.cache_very_stale`` is inline).
 *   - Not dismissible in V0.5 (spec §2.2 / #152 explicit out-of-scope).
 */

const VISIBLE_DEFAULT = 3;
const MAX_ACTIONS = 8;

function SkeletonCard() {
  return (
    <div className="p-4 border border-slate-200 dark:border-slate-700 rounded-xl bg-white dark:bg-slate-800 animate-pulse">
      <div className="h-4 w-2/3 bg-slate-200 dark:bg-slate-700 rounded" />
      <div className="h-3 w-1/2 bg-slate-200 dark:bg-slate-700 rounded mt-3" />
      <div className="h-3 w-3/4 bg-slate-200 dark:bg-slate-700 rounded mt-2" />
      <div className="h-3 w-1/3 bg-slate-200 dark:bg-slate-700 rounded mt-4" />
    </div>
  );
}

function EmptyAllQuiet() {
  return (
    <div
      data-testid="next-actions-empty"
      className="text-center py-8 px-4 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl"
    >
      <div className="text-3xl text-emerald-500 dark:text-emerald-400" aria-hidden="true">
        ✓
      </div>
      <h4 className="mt-2 text-base font-medium text-slate-700 dark:text-slate-200">
        All quiet — no actions need your attention.
      </h4>
      <p className="mt-2 text-sm text-slate-500 dark:text-slate-400 max-w-md mx-auto">
        No expiring legs in the next 14 days. No positions outside their review
        thresholds. Cash is deployed. Run the scanner to find new opportunities.
      </p>
      <div className="mt-4 flex items-center justify-center gap-3">
        <Link
          href="/options"
          data-testid="next-actions-empty-cta-scanner"
          className="inline-flex items-center px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
        >
          Run scanner <span aria-hidden="true" className="ml-1">→</span>
        </Link>
        <Link
          href="/journal"
          data-testid="next-actions-empty-cta-journal"
          className="inline-flex items-center px-4 py-2 rounded-lg border border-slate-300 dark:border-slate-600 text-sm font-medium text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
        >
          Open Journal <span aria-hidden="true" className="ml-1">→</span>
        </Link>
      </div>
    </div>
  );
}

function ErrorCard({ onRetry }) {
  return (
    <div
      data-testid="next-actions-error"
      className="p-4 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl text-sm text-slate-600 dark:text-slate-300 flex items-center justify-between gap-3"
    >
      <span>Couldn’t compute next actions.</span>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-600 text-sm font-medium text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
        >
          Retry
        </button>
      )}
    </div>
  );
}

export default function NextActionsSection({
  actions,
  loading,
  error,
  onRetry,
  onRefreshed,
}) {
  const [expanded, setExpanded] = useState(false);

  // Defensive truncate to MAX_ACTIONS (backend already caps); preserves
  // engine order which is the canonical priority ranking.
  const safeActions = Array.isArray(actions) ? actions.slice(0, MAX_ACTIONS) : [];
  const visibleCount = expanded ? safeActions.length : Math.min(VISIBLE_DEFAULT, safeActions.length);
  const hiddenCount = safeActions.length - visibleCount;

  async function handleInlineCta(action) {
    // The only inline action in V0.5 is ``data.cache_very_stale`` which
    // calls ``refreshStaleCache``. Centralised here so all inline CTAs
    // share the toast + refetch wiring.
    if (action.action_id === 'data.cache_very_stale') {
      try {
        await refreshStaleCache();
        toast.success('Refreshed stale cache entries');
        onRefreshed?.();
      } catch {
        toast.error('Failed to refresh stale cache');
      }
      return;
    }
    // Future inline action types land here.
  }

  return (
    <section
      data-testid="next-actions-section"
      aria-label="Next actions"
      className="space-y-3"
    >
      <h2 className="text-lg font-semibold text-slate-900 dark:text-white">
        Next actions
      </h2>

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3" aria-busy="true">
          <SkeletonCard />
          <SkeletonCard />
          <SkeletonCard />
        </div>
      ) : error ? (
        <ErrorCard onRetry={onRetry} />
      ) : safeActions.length === 0 ? (
        <EmptyAllQuiet />
      ) : (
        <>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            {safeActions.slice(0, visibleCount).map((action) => (
              <NextActionCard
                key={action.id}
                action={action}
                onInlineCta={handleInlineCta}
              />
            ))}
          </div>
          {hiddenCount > 0 && (
            <button
              type="button"
              onClick={() => setExpanded(true)}
              data-testid="next-actions-show-more"
              className="text-sm font-medium text-blue-600 dark:text-blue-400 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
            >
              Show {hiddenCount} more
            </button>
          )}
        </>
      )}
    </section>
  );
}
