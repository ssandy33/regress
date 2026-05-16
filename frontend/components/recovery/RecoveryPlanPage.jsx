// Top-level page for /positions/[id]/recovery.
//
// State machine:
//   - loading             → skeleton
//   - error               → empty state with retry
//   - not-applicable      → EmptyState (option-only or closed)
//   - not-flagged         → EmptyState (position recovered above threshold)
//   - populated           → RecoveryPlanView
//
// Spec: frontend/design-specs/issue-182-recovery-recommendation.md §1.

import Link from 'next/link';
import Header from '../layout/Header';
import { useRecoveryPlan } from '../../hooks/useRecoveryPlan';
import RecoveryPlanView from './RecoveryPlanView';

function formatPct(value) {
  if (value === null || value === undefined) return null;
  return `${(value * 100).toFixed(1)}%`;
}

function formatDollar(value) {
  if (value === null || value === undefined) return null;
  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : '';
  return `${sign}$${abs.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function PositionHeader({ position, state }) {
  if (!position) return null;
  const pct = formatPct(position.pl_pct);
  const pl = formatDollar(position.unrealized_pl);
  return (
    <div data-testid="recovery-position-header">
      <h1 className="text-xl font-semibold text-slate-900 dark:text-white">
        Recovery plan: {position.ticker}
      </h1>
      <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
        {position.shares} sh · basis {formatDollar(position.adjusted_cost_basis)}
        {position.current_price !== null && position.current_price !== undefined
          ? ` · current $${position.current_price.toFixed(2)}`
          : ''}
        {pl !== null && pct !== null
          ? ` · unrealized ${pl} (${pct})`
          : ''}
      </p>
      {state === 'populated' && (
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
          Flagged because P/L breached your review threshold (-5% or -$1,000).
        </p>
      )}
    </div>
  );
}

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

export default function RecoveryPlanPage({ positionId }) {
  const { data, loading, error, refetch } = useRecoveryPlan(positionId);

  return (
    <div
      data-testid="recovery-plan-page"
      className="h-screen flex flex-col bg-slate-100 dark:bg-slate-900"
    >
      <Header sessions={[]} onLoadSession={() => {}} />
      <main className="flex-1 overflow-y-auto p-6 space-y-4">
        <Link
          href="/dashboard"
          className="inline-block text-sm font-medium text-blue-700 dark:text-blue-300 hover:underline"
          data-testid="recovery-back-to-dashboard"
        >
          ← Back to dashboard
        </Link>

        {loading && !data && (
          <div data-testid="recovery-plan-loading" className="space-y-4">
            <div className="h-24 rounded-xl bg-slate-200 dark:bg-slate-700 animate-pulse" />
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
              {[0, 1, 2, 3].map((i) => (
                <div
                  key={i}
                  className="h-64 rounded-xl bg-slate-200 dark:bg-slate-700 animate-pulse"
                />
              ))}
            </div>
          </div>
        )}

        {error && (
          <div
            data-testid="recovery-plan-error"
            className="rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-4 text-sm text-red-700 dark:text-red-300 flex items-center justify-between"
          >
            <span>{error}</span>
            <button
              type="button"
              onClick={refetch}
              className="px-3 py-1.5 rounded-lg bg-red-600 text-white text-sm font-medium hover:bg-red-700"
            >
              Retry
            </button>
          </div>
        )}

        {!error && data && (
          <>
            <PositionHeader position={data.position} state={data.state} />

            {data.state === 'not-applicable' && (
              <EmptyState
                testId="recovery-plan-not-applicable"
                title="Recovery plan not applicable"
                body="This position is closed or holds no shares. The Recovery Plan engine only runs against open share positions that are flagged as underwater."
              />
            )}

            {data.state === 'not-flagged' && (
              <EmptyState
                testId="recovery-plan-not-flagged"
                title="Position is above your review threshold"
                body="The Recovery Plan engine only runs against positions that breach the -5% or -$1,000 review threshold. This position no longer qualifies."
              />
            )}

            {data.state === 'populated' && <RecoveryPlanView data={data} />}
          </>
        )}
      </main>
    </div>
  );
}
