// Top-level page for /positions/[id]/covered-call (issue #247).
//
// State machine (mirrors RecoveryPlanPage / BtcDetailPage):
//   - loading                            → skeleton
//   - error                              → retry banner
//   - applicability = covered_call       → CoveredCallView (populated)
//   - applicability = not_applicable_*   → EmptyState (three sub-states)
//
// The backend's `applicability` field is the source of truth for branching;
// the frontend is a dumb consumer (CLAUDE.md: backend owns the rules).
//
// Spec: frontend/design-specs/issue-247-combined-pnl-and-if-assigned.md §3, §7.

import Link from 'next/link';
import Header from '../layout/Header';
import { useCoveredCallView } from '../../hooks/useCoveredCallView';
import CoveredCallView from './CoveredCallView';

function formatDollar(value, { maximumFractionDigits = 2 } = {}) {
  if (value === null || value === undefined) return '—';
  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : '';
  return `${sign}$${abs.toLocaleString(undefined, {
    minimumFractionDigits: maximumFractionDigits,
    maximumFractionDigits,
  })}`;
}

/**
 * Position-identity header — `Combined P&L: F` title + subtitle line that
 * carries the share count, basis, current price (when present), and a
 * "1 open call" tag derived from per_leg_breakdown.
 */
function PositionHeader({ position, perLegBreakdown }) {
  if (!position) return null;
  const callCount = (perLegBreakdown || []).filter(
    (leg) => leg.type === 'call',
  ).length;
  const callTag =
    callCount === 0
      ? ''
      : ` · ${callCount} open call${callCount === 1 ? '' : 's'}`;
  const currentTag =
    position.current_price === null || position.current_price === undefined
      ? ''
      : ` · current ${formatDollar(position.current_price)}`;
  return (
    <div data-testid="covered-call-position-header">
      <h1 className="text-xl font-semibold text-slate-900 dark:text-white">
        Combined P&amp;L: {position.ticker}
      </h1>
      <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
        {position.shares} sh · basis {formatDollar(position.broker_cost_basis)}
        {currentTag}
        {callTag}
      </p>
    </div>
  );
}

function EmptyState({ testId, title, body, ctaHref, ctaLabel }) {
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
      {ctaHref && (
        <Link
          href={ctaHref}
          className="inline-block mt-4 mr-4 text-sm font-medium text-blue-700 dark:text-blue-300 hover:underline"
        >
          {ctaLabel}
        </Link>
      )}
      <Link
        href="/dashboard"
        className="inline-block mt-4 text-sm font-medium text-blue-700 dark:text-blue-300 hover:underline"
      >
        ← Back to dashboard
      </Link>
    </div>
  );
}

// Disclaimer copy — verbatim from spec §3.6, the project's house framing
// rule. Mandatory: do not soften into recommendations (spec §11).
const FALLBACK_DISCLAIMER =
  'These figures report the position state; they do not recommend an action. Roll / hold / let-assign decisions remain with you.';

export default function CoveredCallPage({ positionId }) {
  const { data, loading, error, refetch } = useCoveredCallView(positionId);

  const applicability = data?.applicability;

  return (
    <div
      data-testid="covered-call-page"
      className="h-screen flex flex-col bg-slate-100 dark:bg-slate-900"
    >
      <Header sessions={[]} onLoadSession={() => {}} />
      <main className="flex-1 overflow-y-auto p-6 space-y-4">
        <Link
          href="/dashboard"
          className="inline-block text-sm font-medium text-blue-700 dark:text-blue-300 hover:underline"
          data-testid="covered-call-back-link"
        >
          ← Back to dashboard
        </Link>

        {loading && !data && (
          <div data-testid="covered-call-loading" className="space-y-4">
            <div className="space-y-2">
              <div className="h-6 w-72 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
              <div className="h-3 w-96 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
            </div>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {[0, 1].map((i) => (
                <div
                  key={i}
                  className="h-56 rounded-xl bg-slate-200 dark:bg-slate-700 animate-pulse"
                />
              ))}
            </div>
            <div className="h-32 rounded-xl bg-slate-200 dark:bg-slate-700 animate-pulse" />
          </div>
        )}

        {error && (
          <div
            data-testid="covered-call-error"
            className="rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-4 text-sm text-red-700 dark:text-red-300 flex items-center justify-between gap-4"
          >
            <span>
              Couldn&apos;t load the combined P&amp;L for this position. Check
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

        {!error && data && (
          <>
            <PositionHeader
              position={data.position}
              perLegBreakdown={data.per_leg_breakdown}
            />

            {applicability === 'not_applicable_no_shares' && (
              <EmptyState
                testId="covered-call-empty-no-shares"
                title="Combined P&L is not applicable"
                body="This position has no shares; the screen reports the net of stock + option legs. CSP-only positions have no stock leg to combine."
              />
            )}

            {applicability === 'not_applicable_no_short_call' && (
              <EmptyState
                testId="covered-call-empty-no-short-call"
                title="No open short call"
                body="Combined P&L for a covered call requires at least one open short call against this position. Sell a call to open one."
                ctaHref="/options"
                ctaLabel="Run scanner →"
              />
            )}

            {applicability === 'not_applicable_closed' && (
              <EmptyState
                testId="covered-call-empty-closed"
                title="Position is closed"
                body="Combined P&L is only computed for open positions."
              />
            )}

            {applicability === 'covered_call' && (
              <CoveredCallView data={data} />
            )}

            {/*
              Footer disclaimer (spec §3.6) — rendered on every state that
              has a payload. Mandatory framing: report, don't advise.
            */}
            <p
              data-testid="covered-call-disclaimer"
              className="text-xs text-slate-500 dark:text-slate-400 mt-4"
            >
              {data.disclaimer || FALLBACK_DISCLAIMER}
            </p>
          </>
        )}
      </main>
    </div>
  );
}
