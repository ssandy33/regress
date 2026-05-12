import Link from 'next/link';
import { useMemo, useState } from 'react';
import Card from '../common/Card';
import EmptyState from '../common/EmptyState';
import { formatRelativeTime } from '../../utils/formatters';

/**
 * RecentActivityCard — diary of saved sessions, imports, and trades.
 *
 * V0.5.4 refactor (issue #153, design-spec §2.7):
 * - Demoted to the bottom of the dashboard (handled by DashboardPage.jsx).
 * - Filter chips: All / Trades / Sessions / Imports (one active at a time;
 *   default "All").
 * - Ticker search input: case-insensitive substring match, client-side only.
 * - Summary line above the list: "N events · last activity {date}".
 * - Empty-with-filter state: "No matching activity" + Clear filters CTA.
 * - `aria-live="polite"` on the row container so screen readers announce when
 *   the filter/search combination changes the visible set.
 *
 * The backend payload (DashboardActivity) currently emits `session_saved` and
 * `trade_added`. The "Imports" chip is wired to `kind === "import"` /
 * `import_started` so a future backend that emits import events lands in the
 * existing UI without another refactor.
 */

const FILTER_KIND_MAP = {
  all: null,
  trades: ['trade_added'],
  sessions: ['session_saved'],
  imports: ['import', 'import_started'],
};

const FILTER_CHIPS = [
  { id: 'all', label: 'All' },
  { id: 'trades', label: 'Trades' },
  { id: 'sessions', label: 'Sessions' },
  { id: 'imports', label: 'Imports' },
];

function describeEvent(event) {
  if (event.kind === 'session_saved') {
    return {
      href: `/analysis?session=${encodeURIComponent(event.session_id ?? '')}`,
      text: (
        <>
          Saved regression session{' '}
          <span className="font-medium">&ldquo;{event.session_name}&rdquo;</span>
        </>
      ),
    };
  }
  if (event.kind === 'trade_added') {
    const friendly = (event.trade_type || '').replace(/_/g, ' ');
    return {
      href: `/journal?position=${encodeURIComponent(event.position_id ?? '')}`,
      text: (
        <>
          New trade: <span className="font-medium">{event.ticker}</span> {friendly}
        </>
      ),
    };
  }
  if (event.kind === 'import' || event.kind === 'import_started') {
    return {
      href: '/import',
      text: (
        <>
          Schwab import{' '}
          {event.ticker ? (
            <>
              — <span className="font-medium">{event.ticker}</span>
            </>
          ) : null}
        </>
      ),
    };
  }
  return { href: '/journal', text: 'Activity' };
}

function ActivityRow({ event }) {
  const { href, text } = describeEvent(event);
  return (
    <Link
      href={href}
      data-testid="dashboard-activity-row"
      className="flex items-baseline gap-3 py-2 border-b border-slate-100 dark:border-slate-700 last:border-b-0 hover:bg-slate-50 dark:hover:bg-slate-700/50 px-2 -mx-2 rounded"
    >
      <span className="w-12 text-xs tabular-nums text-slate-500 dark:text-slate-400">
        {formatRelativeTime(event.timestamp)}
      </span>
      <span className="text-sm text-slate-700 dark:text-slate-200">{text}</span>
    </Link>
  );
}

function FilterChip({ id, label, active, onClick }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      data-testid={`recent-activity-filter-${id}`}
      className={`px-3 py-1 text-xs rounded-full border transition-colors ${
        active
          ? 'bg-blue-600 text-white border-blue-600'
          : 'bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 border-slate-300 dark:border-slate-600 hover:bg-slate-50 dark:hover:bg-slate-700'
      }`}
    >
      {label}
    </button>
  );
}

function summarize(events) {
  if (!events?.length) return null;
  // Latest event determines "last activity"; events are already sorted desc by
  // the backend but we re-pick max defensively in case ordering drifts.
  const latest = events.reduce((acc, e) => {
    if (!acc) return e;
    const a = new Date(acc.timestamp).getTime();
    const b = new Date(e.timestamp).getTime();
    return Number.isFinite(b) && (!Number.isFinite(a) || b > a) ? e : acc;
  }, null);
  return {
    count: events.length,
    lastLabel: latest ? formatRelativeTime(latest.timestamp) : null,
  };
}

export default function RecentActivityCard({ events, loading }) {
  const [filter, setFilter] = useState('all');
  const [query, setQuery] = useState('');

  const summary = useMemo(() => summarize(events), [events]);

  const filtered = useMemo(() => {
    if (!events?.length) return [];
    const kinds = FILTER_KIND_MAP[filter];
    const q = query.trim().toLowerCase();
    return events.filter((event) => {
      if (kinds && !kinds.includes(event.kind)) return false;
      if (q) {
        const ticker = (event.ticker || '').toLowerCase();
        // Case-insensitive substring match per issue #153 implementation rules.
        if (!ticker.includes(q)) return false;
      }
      return true;
    });
  }, [events, filter, query]);

  const hasActiveFilter = filter !== 'all' || query.trim().length > 0;

  const clearFilters = () => {
    setFilter('all');
    setQuery('');
  };

  if (loading) {
    return (
      <Card title="Recent activity" dataTestid="dashboard-activity-card">
        <div className="space-y-2" aria-busy="true">
          {[0, 1, 2, 3, 4].map((i) => (
            <div
              key={i}
              className="h-6 animate-pulse rounded bg-slate-200 dark:bg-slate-700"
            />
          ))}
        </div>
      </Card>
    );
  }

  // Card body — controls always render when there are events to filter; the
  // pristine empty state (no events at all) skips controls so we don't suggest
  // filtering nothing.
  const hasEvents = (events?.length ?? 0) > 0;

  return (
    <Card title="Recent activity" dataTestid="dashboard-activity-card">
      {hasEvents ? (
        <>
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between mb-3">
            <div
              data-testid="recent-activity-summary"
              className="text-xs text-slate-500 dark:text-slate-400"
            >
              {summary
                ? `${summary.count} event${summary.count === 1 ? '' : 's'}${
                    summary.lastLabel ? ` · last activity ${summary.lastLabel}` : ''
                  }`
                : ''}
            </div>
            <div className="flex items-center gap-2">
              <input
                type="search"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search ticker"
                aria-label="Filter by ticker"
                data-testid="recent-activity-search"
                className="w-full sm:w-40 px-3 py-1 text-sm rounded-md border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-800 text-slate-700 dark:text-slate-200 placeholder:text-slate-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
              />
            </div>
          </div>

          <div className="flex flex-wrap gap-2 mb-3">
            {FILTER_CHIPS.map((chip) => (
              <FilterChip
                key={chip.id}
                id={chip.id}
                label={chip.label}
                active={filter === chip.id}
                onClick={() => setFilter(chip.id)}
              />
            ))}
          </div>

          <div aria-live="polite">
            {filtered.length ? (
              <div>
                {filtered.map((event, i) => (
                  <ActivityRow
                    key={`${event.kind}-${event.timestamp}-${i}`}
                    event={event}
                  />
                ))}
              </div>
            ) : (
              <div className="text-center py-6 px-4">
                <p className="text-sm text-slate-500 dark:text-slate-400">
                  No matching activity
                </p>
                {hasActiveFilter ? (
                  <button
                    type="button"
                    onClick={clearFilters}
                    data-testid="recent-activity-clear-filters"
                    className="mt-2 inline-flex items-center text-sm text-blue-600 dark:text-blue-400 hover:underline focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500 rounded"
                  >
                    Clear filters →
                  </button>
                ) : null}
              </div>
            )}
          </div>
        </>
      ) : (
        <EmptyState
          title="No activity yet"
          description="Saved sessions, imports, and trades will appear here."
        />
      )}
    </Card>
  );
}
