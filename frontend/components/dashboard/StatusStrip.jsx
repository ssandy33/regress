import StatusPill from '../common/StatusPill';

/**
 * StatusStrip — four health pills always rendered above the KPI row.
 *
 * Each pill is a Link (via StatusPill) to the relevant Settings deep-link.
 * Hash-based deep-linking is forward-looking — Settings doesn't yet scroll-to
 * a section based on the hash; that's a follow-up.
 */
function schwabPill(schwab) {
  if (!schwab?.configured) {
    return { state: 'error', label: 'Schwab not connected' };
  }
  if (!schwab.valid) {
    return { state: 'warn', label: 'Schwab token expiring' };
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
  if (!cache || cache.total === 0) {
    return { state: 'neutral', label: 'Cache empty' };
  }
  if (cache.very_stale > 0) {
    return { state: 'error', label: `Cache very stale (${cache.very_stale})` };
  }
  if (cache.stale > 0) {
    return { state: 'warn', label: `Cache stale (${cache.stale})` };
  }
  return { state: 'ok', label: 'Cache fresh' };
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
      <StatusPill {...cache} href="/settings#cache" dataTestid="status-pill-cache" />
      <StatusPill {...journal} href="/journal" dataTestid="status-pill-journal" />
    </div>
  );
}
