/**
 * Section D — Financial scorecard (issue #280, design spec §4 Section D).
 *
 * Renders a 2×2 grid of stat tiles, each with a sparkline + QoQ and YoY
 * delta pills. Sparklines are native SVG (no Plotly) — 8 points per tile
 * is too small to warrant a charting library.
 *
 * Per design spec the missing-quarter and missing-metric cases each have
 * their own visual treatment:
 *   - Fewer than 4 quarters → render available points + show QoQ only;
 *     YoY renders as "—" with the rationale exposed via `title` attribute.
 *   - A specific metric absent for the latest quarter → tile renders at
 *     `opacity-60` with "Not reported" copy.
 */

function FailureTile({ source, error, onRetry }) {
  // Issue #288: branch on the backend detail string.
  //  - "...throttling..."          → Yahoo throttled headline
  //  - "No financial data..."      → render the backend detail verbatim
  //                                  (already names the ticker + both sources)
  //  - everything else             → generic "couldn't load" copy
  const isThrottled =
    typeof error === 'string' && error.includes('throttling');
  const isNoData =
    typeof error === 'string' &&
    error.startsWith('No financial data available');
  let headline;
  if (isThrottled) {
    headline = 'Yahoo Finance is throttling us — try again in a few minutes.';
  } else if (isNoData) {
    headline = error;
  } else {
    headline = "We couldn't load this — retry";
  }
  return (
    <div data-testid="research-d-error" className="text-sm">
      <p className="text-amber-600 dark:text-amber-400">
        <span aria-hidden="true">⚠</span> {headline}
      </p>
      {!isThrottled && !isNoData && (
        <p className="text-slate-500 dark:text-slate-400 mt-1">
          Source unavailable: {source || 'financials'}
        </p>
      )}
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
      data-testid="research-d-skeleton"
      className="grid grid-cols-1 sm:grid-cols-2 gap-4"
      aria-busy="true"
    >
      {[0, 1, 2, 3].map((i) => (
        <div
          key={i}
          className="h-32 rounded-lg bg-slate-200 dark:bg-slate-700 animate-pulse"
        />
      ))}
    </div>
  );
}

function Sparkline({ points }) {
  // points: numeric array, oldest → newest.
  const series = points.filter((v) => v !== null && v !== undefined);
  if (series.length < 2) {
    return (
      <svg
        className="w-full h-12"
        viewBox="0 0 100 30"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <line
          x1="0"
          y1="15"
          x2="100"
          y2="15"
          stroke="rgb(148 163 184)"
          strokeDasharray="2 2"
        />
      </svg>
    );
  }
  const min = Math.min(...series);
  const max = Math.max(...series);
  const range = max - min || 1;
  const stepX = 100 / (series.length - 1);
  const yFor = (v) => 28 - ((v - min) / range) * 24;
  const path = series
    .map((v, i) => `${i === 0 ? 'M' : 'L'} ${i * stepX} ${yFor(v)}`)
    .join(' ');
  const lastX = (series.length - 1) * stepX;
  const lastY = yFor(series[series.length - 1]);

  return (
    <svg
      className="w-full h-12"
      viewBox="0 0 100 30"
      preserveAspectRatio="none"
      aria-hidden="true"
    >
      <path d={path} fill="none" stroke="rgb(59 130 246)" strokeWidth="1.5" />
      <circle cx={lastX} cy={lastY} r="1.8" fill="rgb(59 130 246)" />
    </svg>
  );
}

function deltaClass(value) {
  if (value === null || value === undefined) return 'text-slate-400';
  if (value > 0) return 'text-emerald-600 dark:text-emerald-400';
  if (value < 0) return 'text-rose-600 dark:text-rose-400';
  return 'text-slate-400';
}

function formatPct(value) {
  if (value === null || value === undefined) return '—';
  const sign = value > 0 ? '▲ ' : value < 0 ? '▼ ' : '';
  return `${sign}${Math.abs(value * 100).toFixed(1)}%`;
}

function formatPctPoints(value) {
  if (value === null || value === undefined) return '—';
  const sign = value > 0 ? '▲ ' : value < 0 ? '▼ ' : '';
  return `${sign}${Math.abs(value * 100).toFixed(1)}pp`;
}

function formatRevenue(value) {
  if (value === null || value === undefined) return '—';
  if (Math.abs(value) >= 1e9) return `$${(value / 1e9).toFixed(2)}B`;
  if (Math.abs(value) >= 1e6) return `$${(value / 1e6).toFixed(1)}M`;
  return `$${Math.round(value).toLocaleString()}`;
}

function formatEps(value) {
  if (value === null || value === undefined) return '—';
  const sign = value < 0 ? '−' : '';
  return `${sign}$${Math.abs(value).toFixed(2)}`;
}

function formatMargin(value) {
  if (value === null || value === undefined) return '—';
  return `${(value * 100).toFixed(0)}%`;
}

function computeQoQ(values) {
  // values: oldest → newest
  if (values.length < 2) return null;
  const last = values[values.length - 1];
  const prev = values[values.length - 2];
  if (last === null || last === undefined || prev === null || prev === undefined) {
    return null;
  }
  if (prev === 0) return null;
  return (last - prev) / Math.abs(prev);
}

function computeYoY(values) {
  if (values.length < 5) return null;
  const last = values[values.length - 1];
  const yearAgo = values[values.length - 5];
  if (last === null || last === undefined || yearAgo === null || yearAgo === undefined) {
    return null;
  }
  if (yearAgo === 0) return null;
  return (last - yearAgo) / Math.abs(yearAgo);
}

function ScoreTile({
  testId,
  label,
  values,
  formatValue,
  formatDelta = formatPct,
  ariaLabel,
}) {
  // values: ordered oldest → newest. The payload from the backend comes
  // newest-first; the page reverses before passing in here.
  const last = values[values.length - 1];
  const qoq = computeQoQ(values);
  const yoy = computeYoY(values);
  const missing = last === null || last === undefined;

  return (
    <div
      data-testid={testId}
      aria-label={ariaLabel}
      className={`rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900/40 p-4 ${
        missing ? 'opacity-60' : ''
      }`}
    >
      <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {label}
      </div>
      <div className="mt-1 flex items-center justify-between">
        <span className="text-2xl font-semibold tabular-nums text-slate-900 dark:text-white">
          {formatValue(last)}
        </span>
        <span className={`text-xs tabular-nums ${deltaClass(qoq)}`}>
          {qoq === null ? '—' : `${formatDelta(qoq)} QoQ`}
        </span>
      </div>
      <div className="mt-2">
        <Sparkline points={values} />
      </div>
      <div className={`mt-1 text-xs tabular-nums ${deltaClass(yoy)}`}>
        {yoy === null ? (
          <span title="Need 4+ quarters for YoY">— YoY</span>
        ) : (
          `${formatDelta(yoy)} YoY`
        )}
      </div>
      {missing && (
        <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
          Not reported
        </div>
      )}
    </div>
  );
}

export default function FinancialScorecard({ data, loading, error, onRetry }) {
  let body;
  if (loading && !data) {
    body = <Skeleton />;
  } else if (error && !data) {
    body = <FailureTile source="alphavantage" error={error} onRetry={onRetry} />;
  } else if (data) {
    // The backend ships newest-first; sparklines want oldest-first.
    const quarters = [...(data.quarters || [])].reverse();
    const revenue = quarters.map((q) => q.revenue);
    const eps = quarters.map((q) => q.eps);
    const grossMargin = quarters.map((q) => q.gross_margin);
    const opMargin = quarters.map((q) => q.operating_margin);
    body = (
      <>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <ScoreTile
            testId="research-d-tile-revenue"
            label="Revenue"
            ariaLabel="Revenue trend over last 8 quarters"
            values={revenue}
            formatValue={formatRevenue}
          />
          <ScoreTile
            testId="research-d-tile-eps"
            label="EPS"
            ariaLabel="Earnings per share trend over last 8 quarters"
            values={eps}
            formatValue={formatEps}
          />
          <ScoreTile
            testId="research-d-tile-gross-margin"
            label="Gross margin"
            ariaLabel="Gross margin trend over last 8 quarters"
            values={grossMargin}
            formatValue={formatMargin}
            formatDelta={formatPctPoints}
          />
          <ScoreTile
            testId="research-d-tile-operating-margin"
            label="Operating margin"
            ariaLabel="Operating margin trend over last 8 quarters"
            values={opMargin}
            formatValue={formatMargin}
            formatDelta={formatPctPoints}
          />
        </div>
        <div
          data-testid="research-d-source-caption"
          className="mt-3 text-xs text-slate-500 dark:text-slate-400"
        >
          {data.source === 'yfinance'
            ? `Source: yfinance (alphavantage rate-limited)`
            : `Source: ${data.source || 'alphavantage'}`}
          {data.fetched_at ? ` · refreshed ${data.fetched_at}` : ''}
        </div>
      </>
    );
  } else {
    body = null;
  }

  return (
    <section
      data-testid="research-d"
      aria-labelledby="research-d-heading"
      className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-5"
    >
      <h2
        id="research-d-heading"
        className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400"
      >
        D · Financial scorecard (last 8 quarters)
      </h2>
      <div className="mt-3">{body}</div>
    </section>
  );
}
