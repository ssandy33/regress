"use client";

import Link from 'next/link';
import Header from '../layout/Header';
import { useStockResearch } from '../../hooks/useStockResearch';
import BusinessSnapshotCard from './BusinessSnapshotCard';
import ResearchPriceChart from './ResearchPriceChart';
import FinancialScorecard from './FinancialScorecard';
import RegressionInsightCard from './RegressionInsightCard';
import ThesisNoteEditor from './ThesisNoteEditor';
import PositionHeader from './PositionHeader';
import DataCaveatsFooter from './DataCaveatsFooter';

/**
 * StockResearchPage — top-level state machine for /positions/[id]/review
 * (issue #280).
 *
 * Mirrors the recovery / BTC page-state contract:
 *
 *   loading   → page skeleton (mirrors the populated layout for CLS-stability)
 *   not-found → centered EmptyState (full-page 404)
 *   error     → red retry banner (transient backend failures)
 *   populated → header + 6 sections + footer
 *
 * Per-section failures are handled INSIDE each section component (NFR-3 /
 * design spec §7) — only a hard-fail on the *position* itself collapses
 * the page to the full-page error/404 state.
 */

function FullPageError({ message, onRetry }) {
  return (
    <div
      data-testid="research-error"
      className="rounded-xl bg-red-50 dark:bg-red-900/20 border border-red-200 dark:border-red-800 p-4 text-sm text-red-700 dark:text-red-300 flex items-center justify-between gap-4"
    >
      <span>{message || "Couldn't load this position."}</span>
      <button
        type="button"
        onClick={onRetry}
        className="px-3 py-1.5 rounded-lg bg-red-600 text-white text-sm font-medium hover:bg-red-700 shrink-0"
      >
        Retry
      </button>
    </div>
  );
}

function NotFound() {
  return (
    <div
      data-testid="research-not-found"
      className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-6 text-center"
    >
      <h2 className="text-base font-semibold text-slate-900 dark:text-white">
        That position isn&apos;t on file
      </h2>
      <p className="text-sm text-slate-500 dark:text-slate-400 mt-2 max-w-prose mx-auto">
        It may have been deleted or never existed.
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

function FullPageSkeleton() {
  return (
    <div data-testid="research-loading" className="space-y-6">
      <div className="h-20 rounded-xl bg-slate-200 dark:bg-slate-700 animate-pulse" />
      <div className="h-40 rounded-xl bg-slate-200 dark:bg-slate-700 animate-pulse" />
      <div className="h-72 rounded-xl bg-slate-200 dark:bg-slate-700 animate-pulse" />
      <div className="h-48 rounded-xl bg-slate-200 dark:bg-slate-700 animate-pulse" />
      <div className="h-60 rounded-xl bg-slate-200 dark:bg-slate-700 animate-pulse" />
      <div className="h-48 rounded-xl bg-slate-200 dark:bg-slate-700 animate-pulse" />
    </div>
  );
}

export default function StockResearchPage({ positionId }) {
  const {
    position,
    business,
    priceHistory,
    financials,
    regression,
    thesis,
    refetchSection,
    refetchAll,
  } = useStockResearch(positionId);

  const positionData = position.data;
  const positionStatus = position.status;
  const positionLoading = position.loading;
  const positionError = position.error;

  return (
    <div
      data-testid="research-page"
      className="min-h-screen flex flex-col bg-slate-100 dark:bg-slate-900"
    >
      <Header sessions={[]} onLoadSession={() => {}} />
      <main className="flex-1 max-w-4xl w-full mx-auto px-6 py-8 space-y-6">
        <Link
          href="/dashboard"
          data-testid="research-back-to-dashboard"
          className="inline-block text-sm font-medium text-blue-700 dark:text-blue-300 hover:underline"
        >
          ← Back to dashboard
        </Link>

        {positionLoading && !positionData && <FullPageSkeleton />}

        {!positionLoading && positionStatus === 404 && <NotFound />}

        {!positionLoading && positionError && positionStatus !== 404 && (
          <FullPageError message={positionError} onRetry={refetchAll} />
        )}

        {positionData && (
          <>
            <PositionHeader position={positionData} business={business.data} />

            <BusinessSnapshotCard
              data={business.data}
              loading={business.loading}
              error={business.error}
              onRetry={() => refetchSection('business')}
            />

            <ResearchPriceChart
              data={priceHistory.data}
              loading={priceHistory.loading}
              error={priceHistory.error}
              onRetry={() => refetchSection('priceHistory')}
            />

            <FinancialScorecard
              data={financials.data}
              loading={financials.loading}
              error={financials.error}
              onRetry={() => refetchSection('financials')}
            />

            <RegressionInsightCard
              data={regression.data}
              loading={regression.loading}
              error={regression.error}
              onRetry={() => refetchSection('regression')}
            />

            <ThesisNoteEditor
              ticker={positionData.ticker}
              data={thesis.data}
              loading={thesis.loading}
              error={thesis.error}
              onRetry={() => refetchSection('thesis')}
              saveThesis={thesis.save}
            />

            <DataCaveatsFooter
              business={business.data}
              financials={financials.data}
              regression={regression.data}
            />
          </>
        )}
      </main>
    </div>
  );
}
