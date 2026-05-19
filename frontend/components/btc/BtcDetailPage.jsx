// Top-level page for /positions/[id]/legs/[legId]/btc.
//
// State machine (mirrors RecoveryPlanPage, with one extra leaf):
//   - loading             → skeleton
//   - error               → red retry banner
//   - not-found           → EmptyState (HTTP 404 — unknown / closed leg)
//   - no-rule-triggered   → BtcDetailView (verdict 'hold' — no Buy-to-close CTA)
//   - populated           → BtcDetailView (a rule fired)
//
// Spec: frontend/design-specs/issue-244-btc-detail-screen.md §1, §7.

import Link from 'next/link';
import Header from '../layout/Header';
import { useBtcDetail } from '../../hooks/useBtcDetail';
import BtcDetailView from './BtcDetailView';

function EmptyState({ testId, title, body }) {
  return (
    <div
      data-testid={testId}
      className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-6 text-center"
    >
      <h2 className="text-base font-semibold text-slate-900 dark:text-white">
        {title}
      </h2>
      <p className="text-sm text-slate-500 dark:text-slate-400 mt-2 max-w-prose mx-auto">
        {body}
      </p>
      <Link
        href="/dashboard"
        className="inline-block mt-4 text-sm font-medium text-blue-700 dark:text-blue-300 hover:underline"
      >
        ← Back to dashboard
      </Link>
    </div>
  );
}

export default function BtcDetailPage({ positionId, legId }) {
  const { data, loading, error, refetch } = useBtcDetail(positionId, legId);

  const state = data?.state || null;
  const isNoRule = state === 'no-rule-triggered';
  // The page root testid distinguishes the no-rule variant from populated.
  const pageTestId = isNoRule ? 'btc-detail-no-rule' : 'btc-detail-page';

  return (
    <div className="h-screen flex flex-col bg-slate-100 dark:bg-slate-900">
      <Header sessions={[]} onLoadSession={() => {}} />
      <main
        data-testid={
          !error && data && (state === 'populated' || isNoRule)
            ? pageTestId
            : undefined
        }
        className="flex-1 overflow-y-auto p-6 space-y-4"
      >
        <Link
          href="/dashboard"
          className="inline-block text-sm font-medium text-blue-700 dark:text-blue-300 hover:underline"
          data-testid="btc-detail-back-to-dashboard"
        >
          ← Back to dashboard
        </Link>

        {loading && !data && (
          <div data-testid="btc-detail-loading" className="space-y-4">
            <div className="space-y-2">
              <div className="h-6 w-72 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
              <div className="h-3 w-96 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
            </div>
            <div className="h-24 rounded-xl bg-slate-200 dark:bg-slate-700 animate-pulse" />
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[0, 1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="h-24 rounded-xl bg-slate-200 dark:bg-slate-700 animate-pulse"
                />
              ))}
            </div>
            <div className="h-40 rounded-xl bg-slate-200 dark:bg-slate-700 animate-pulse" />
          </div>
        )}

        {error && (
          <div
            data-testid="btc-detail-error"
            className="rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-4 text-sm text-red-700 dark:text-red-300 flex items-center justify-between gap-4"
          >
            <span>
              Couldn&apos;t load the buy-to-close detail for this leg. Check
              your connection and try again.
            </span>
            <button
              type="button"
              onClick={refetch}
              className="px-3 py-1.5 rounded-lg bg-red-600 text-white text-sm font-medium hover:bg-red-700 shrink-0"
            >
              Retry
            </button>
          </div>
        )}

        {!error && data && state === 'not-found' && (
          <EmptyState
            testId="btc-detail-not-found"
            title="Leg not found"
            body="This option leg doesn't exist, or it has been closed. Buy-to-close review is only available for open option legs."
          />
        )}

        {!error && data && (state === 'populated' || isNoRule) && (
          <BtcDetailView data={data} />
        )}
      </main>
    </div>
  );
}
