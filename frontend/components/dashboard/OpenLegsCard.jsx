import Link from 'next/link';
import Card from '../common/Card';
import EmptyState from '../common/EmptyState';
import { formatPercent } from '../../utils/formatters';

function dteBadgeClass(dte) {
  if (dte <= 7) return 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300';
  if (dte <= 14) return 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300';
  return 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-200';
}

function moneynessText(moneyness) {
  if (!moneyness) return <span className="text-slate-400">—</span>;
  if (moneyness.state === 'ITM') {
    return (
      <span className="text-red-600 dark:text-red-400">
        ITM by ${moneyness.distance_dollars.toFixed(2)}
      </span>
    );
  }
  if (moneyness.state === 'ATM') {
    return <span className="text-yellow-600 dark:text-yellow-400">ATM</span>;
  }
  return (
    <span className="text-slate-600 dark:text-slate-300">
      OTM {formatPercent(moneyness.distance_pct, 1)}
    </span>
  );
}

function LegRow({ leg }) {
  return (
    <Link
      href={`/journal?position=${encodeURIComponent(leg.position_id)}`}
      data-testid="dashboard-leg-row"
      className="grid grid-cols-12 gap-2 items-center py-2 border-b border-slate-100 dark:border-slate-700 last:border-b-0 hover:bg-slate-50 dark:hover:bg-slate-700/50 px-2 -mx-2 rounded text-sm"
    >
      <span className="col-span-2 font-semibold text-slate-900 dark:text-white">
        {leg.ticker}
      </span>
      <span className="col-span-2 tabular-nums text-slate-700 dark:text-slate-200">
        {leg.strike} {leg.type === 'put' ? 'P' : 'C'}
      </span>
      <span className="col-span-3 tabular-nums text-slate-600 dark:text-slate-300">
        {leg.expiration}
      </span>
      <span className="col-span-2">
        <span
          className={`inline-block px-2 py-0.5 text-xs rounded-full ${dteBadgeClass(leg.dte)}`}
        >
          {leg.dte}d
        </span>
      </span>
      <span className="col-span-3 truncate">{moneynessText(leg.moneyness)}</span>
    </Link>
  );
}

export default function OpenLegsCard({ legs, loading }) {
  if (loading) {
    return (
      <Card title="Open option legs" dataTestid="dashboard-legs-card">
        <div className="space-y-2" aria-busy="true">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-7 animate-pulse rounded bg-slate-200 dark:bg-slate-700"
            />
          ))}
        </div>
      </Card>
    );
  }

  return (
    <Card
      title="Open option legs"
      dataTestid="dashboard-legs-card"
      footer={
        <Link
          href="/options"
          className="text-blue-600 dark:text-blue-400 hover:underline"
        >
          → View all in Options
        </Link>
      }
    >
      {legs?.length ? (
        <div>
          {legs.map((leg) => (
            <LegRow key={leg.id} leg={leg} />
          ))}
          <div className="text-xs text-slate-500 dark:text-slate-400 pt-3">
            Showing {legs.length} of {legs.length} open legs
          </div>
        </div>
      ) : (
        <EmptyState
          title="No open option legs"
          description="Sold puts and calls will appear here once you log a trade."
          primaryAction={{ label: 'Open Options', href: '/options' }}
        />
      )}
    </Card>
  );
}
