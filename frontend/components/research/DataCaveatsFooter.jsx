/**
 * Data caveats footer (issue #280, design spec §2 + §5).
 *
 * Single tile at the bottom of the page listing the aggregate sources +
 * the latest refresh timestamp + the not-investment-advice disclaimer.
 * Source pills are aggregated here (NOT surfaced per-section) per the
 * design spec recommendation.
 */
function uniqueSources(sections) {
  const set = new Set();
  sections.forEach((s) => {
    if (s?.source) set.add(s.source);
  });
  return Array.from(set);
}

function latestRefresh(sections) {
  const stamps = sections
    .map((s) => s?.fetched_at)
    .filter(Boolean)
    .sort();
  if (!stamps.length) return null;
  return stamps[stamps.length - 1];
}

export default function DataCaveatsFooter({ business, financials, regression }) {
  const sources = uniqueSources([business, financials, regression]);
  const refresh = latestRefresh([business, financials, regression]);
  const sourceLine = sources.length
    ? `${sources.join(' · ')} · FRED · your trades.`
    : 'yfinance · alphavantage · FRED · your trades.';

  return (
    <section className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-5">
      <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
        Data &amp; caveats
      </h3>
      <p
        data-testid="research-footer-sources"
        className="mt-2 text-sm text-slate-700 dark:text-slate-200"
      >
        Sources: {sourceLine}
      </p>
      <p
        data-testid="research-footer-refreshed"
        className="mt-1 text-xs text-slate-500 dark:text-slate-400"
      >
        Last refresh: {refresh || 'unknown'}
      </p>
      <p
        data-testid="research-footer-disclaimer"
        className="mt-2 text-xs text-slate-500 dark:text-slate-400"
      >
        Not investment advice. Cached per Source pill on each section. The
        regression decomposes recent price behavior — it is not a prediction.
      </p>
    </section>
  );
}
