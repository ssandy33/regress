import { useState } from 'react';

/**
 * Section A — Business snapshot card (issue #280, design spec §4 Section A).
 *
 * - Long-summary paragraph truncated at ~280 chars; a "Show more" toggle
 *   reveals the full body. State is component-local — toggling does NOT
 *   persist across navigations (spec §4 Section A).
 * - 4-up KV strip (Sector / Industry / Market cap / Employees). 2-up on
 *   mobile.
 * - Per-section failure tile when the upstream returns nothing —
 *   amber-warning iconography (not rose) because the page still works.
 *
 * The card frame stays visible even in the failure state so the user can
 * still see "this is Section A". Loading skeleton mirrors the populated
 * layout to keep the cumulative-layout-shift score honest.
 */

const SUMMARY_TRUNCATE_AT = 280;

function FailureTile({ source, onRetry }) {
  return (
    <div data-testid="research-a-error" className="text-sm">
      <p className="text-amber-600 dark:text-amber-400">
        <span aria-hidden="true">⚠</span> We couldn&apos;t load this — retry
      </p>
      <p className="text-slate-500 dark:text-slate-400 mt-1">
        Source unavailable: {source || 'yfinance'}
      </p>
      <button
        type="button"
        onClick={onRetry}
        className="mt-3 px-3 py-1.5 rounded-lg bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-200 text-sm font-medium hover:bg-slate-200 dark:hover:bg-slate-600"
      >
        Retry
      </button>
    </div>
  );
}

function Skeleton() {
  return (
    <div
      data-testid="research-a-skeleton"
      className="space-y-3"
      aria-busy="true"
    >
      <div className="h-3 rounded bg-slate-200 dark:bg-slate-700 animate-pulse" />
      <div className="h-3 rounded bg-slate-200 dark:bg-slate-700 animate-pulse w-11/12" />
      <div className="h-3 rounded bg-slate-200 dark:bg-slate-700 animate-pulse w-10/12" />
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4">
        {[0, 1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-14 rounded bg-slate-200 dark:bg-slate-700 animate-pulse"
          />
        ))}
      </div>
    </div>
  );
}

function formatMarketCap(value) {
  if (value === null || value === undefined) return '—';
  const abs = Math.abs(value);
  if (abs >= 1e12) return `$${(value / 1e12).toFixed(1)}T`;
  if (abs >= 1e9) return `$${(value / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `$${(value / 1e6).toFixed(1)}M`;
  return `$${Math.round(value).toLocaleString()}`;
}

function formatEmployees(value) {
  if (value === null || value === undefined) return '—';
  return value.toLocaleString();
}

function KvTile({ testId, label, value }) {
  return (
    <div
      data-testid={testId}
      className="rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40 p-3"
    >
      <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {label}
      </div>
      <div className="mt-1 text-sm font-medium text-slate-900 dark:text-white tabular-nums">
        {value ?? '—'}
      </div>
    </div>
  );
}

export default function BusinessSnapshotCard({ data, loading, error, onRetry }) {
  const [expanded, setExpanded] = useState(false);
  const summary = data?.summary || '';
  const truncated =
    summary.length > SUMMARY_TRUNCATE_AT
      ? `${summary.slice(0, SUMMARY_TRUNCATE_AT)}…`
      : summary;
  const showToggle = summary.length > SUMMARY_TRUNCATE_AT;

  return (
    <section
      data-testid="research-a"
      aria-labelledby="research-a-heading"
      className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-5"
    >
      <h2
        id="research-a-heading"
        className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400"
      >
        A · Business snapshot
      </h2>

      {loading && !data ? (
        <div className="mt-4">
          <Skeleton />
        </div>
      ) : error && !data ? (
        <div className="mt-4">
          <FailureTile source="yfinance" onRetry={onRetry} />
        </div>
      ) : data ? (
        <>
          <p
            data-testid="research-a-business-summary"
            className="mt-3 text-sm text-slate-700 dark:text-slate-200 leading-relaxed"
          >
            {expanded ? summary : truncated || '—'}
          </p>
          {showToggle && (
            <button
              type="button"
              data-testid="research-a-show-more"
              onClick={() => setExpanded((v) => !v)}
              className="mt-2 text-sm text-blue-600 dark:text-blue-400 hover:underline"
            >
              {expanded ? 'Show less' : 'Show more'}
            </button>
          )}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mt-5">
            <KvTile
              testId="research-a-kv-sector"
              label="Sector"
              value={data.sector}
            />
            <KvTile
              testId="research-a-kv-industry"
              label="Industry"
              value={data.industry}
            />
            <KvTile
              testId="research-a-kv-market-cap"
              label="Market cap"
              value={formatMarketCap(data.market_cap)}
            />
            <KvTile
              testId="research-a-kv-employees"
              label="Employees"
              value={formatEmployees(data.employees)}
            />
          </div>
        </>
      ) : null}
    </section>
  );
}
