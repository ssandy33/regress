import StatusPill from '../common/StatusPill';
import { formatQuoteAge } from '../../utils/formatters';

/**
 * StatusStrip — four health pills always rendered above the KPI row.
 *
 * Each pill is a Link (via StatusPill) to the relevant Settings deep-link.
 * Hash-based deep-linking is forward-looking — Settings doesn't yet scroll-to
 * a section based on the hash; that's a follow-up.
 */

// Very-stale budget (seconds) that flips the freshness pill red. MUST match
// ``QUOTE_VERY_STALE_BUDGET_SECONDS`` in backend/app/services/dashboard.py — the
// backend already flags per-symbol staleness at the 15m intraday budget
// (``displayed_stale``); this threshold only escalates the pill to ``very_stale``
// once the oldest shown quote crosses an hour (#417 R5).
const VERY_STALE_BUDGET_SECONDS = 60 * 60;
// Intraday freshness budget, shown in the pill hover so the user knows the bar.
const FRESH_BUDGET_LABEL = '15m';
function schwabPill(schwab) {
  if (!schwab?.configured) {
    return { state: 'error', label: 'Schwab not connected' };
  }
  if (!schwab.valid) {
    // Issue #277: ``schwab.error`` is non-null when the parallel quote /
    // option-chain fans failed during this dashboard load. Both branches
    // stay on the existing ``warn`` (yellow) state — the visual language is
    // already correct; only the label needs to disambiguate "token
    // expiring" from "live calls failing".
    return {
      state: 'warn',
      label: schwab.error ? 'Schwab calls failing' : 'Schwab token expiring',
    };
  }
  return { state: 'ok', label: 'Schwab connected' };
}

function fredPill(fred) {
  if (!fred?.configured) {
    return { state: 'error', label: 'FRED not configured' };
  }
  if (!fred.valid) {
    return { state: 'warn', label: 'FRED key set, validation failed' };
  }
  return { state: 'ok', label: 'FRED connected' };
}

function cachePill(cache) {
  // Honest freshness (#417 / PRD #415 R5): the dashboard pill is driven by the
  // OLDEST displayed live quote, NOT the research/data cache buckets (which age
  // in days and are a different concern — they stay in Settings → Data Sources).
  // With no assessable quotes shown there is nothing to report → skip the pill.
  const displayedTotal = cache?.displayed_total ?? 0;
  if (!cache || displayedTotal === 0) {
    return null;
  }
  const displayedStale = cache.displayed_stale ?? 0;
  const stalestAge = cache.stalest_age_seconds;
  const stalestSymbol = cache.stalest_symbol;

  if (displayedStale > 0) {
    const veryStale =
      stalestAge != null && stalestAge >= VERY_STALE_BUDGET_SECONDS;
    const hover = stalestSymbol
      ? `Stalest quote: ${stalestSymbol} · ${formatQuoteAge(stalestAge)} ago (budget ${FRESH_BUDGET_LABEL})`
      : undefined;
    return {
      state: veryStale ? 'error' : 'warn',
      label: `Quotes ${veryStale ? 'very stale' : 'stale'} (${displayedStale})`,
      freshnessState: veryStale ? 'very_stale' : 'stale',
      title: hover,
    };
  }
  return { state: 'ok', label: 'Quotes fresh', freshnessState: 'fresh' };
}

function journalPill(journal) {
  const count = journal?.positions_count ?? 0;
  return { state: 'neutral', label: `Journal ${count} positions` };
}

export default function StatusStrip({ status }) {
  const schwab = schwabPill(status?.schwab);
  const fred = fredPill(status?.fred);
  const cache = cachePill(status?.cache);
  const journal = journalPill(status?.journal);

  return (
    <div
      data-testid="dashboard-status-strip"
      className="flex flex-wrap items-center gap-2"
    >
      <StatusPill {...schwab} href="/settings#schwab" dataTestid="status-pill-schwab" />
      <StatusPill {...fred} href="/settings#fred" dataTestid="status-pill-fred" />
      {cache && (
        <StatusPill
          state={cache.state}
          label={cache.label}
          title={cache.title}
          href="/settings#cache"
          dataTestid="status-pill-cache"
          dataAttrs={{ 'data-freshness-state': cache.freshnessState }}
        />
      )}
      <StatusPill {...journal} href="/journal" dataTestid="status-pill-journal" />
    </div>
  );
}
