import Link from 'next/link';
import Card from '../common/Card';
import EmptyState from '../common/EmptyState';

const TAG_PILL = {
  'roll-or-assign': 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  manage: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300',
  watch: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300',
  hold: 'bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-200',
};

const TAG_LABEL = {
  'roll-or-assign': 'Roll or assign',
  manage: 'Manage',
  watch: 'Watch',
  hold: 'Hold',
};

const TAG_ICON = {
  'roll-or-assign': '⚠',
  manage: '⚠',
  watch: '●',
  hold: '',
};

function ExpirationRow({ leg }) {
  const tag = leg.decision_tag;
  return (
    <Link
      href={`/journal?position=${encodeURIComponent(leg.position_id)}`}
      data-testid="dashboard-expiration-row"
      className="block py-3 border-b border-slate-100 dark:border-slate-700 last:border-b-0 hover:bg-slate-50 dark:hover:bg-slate-700/50 px-2 -mx-2 rounded"
    >
      <div className="flex items-baseline gap-2">
        {TAG_ICON[tag] && (
          <span
            className={
              tag === 'roll-or-assign' || tag === 'manage'
                ? 'text-red-500'
                : 'text-yellow-500'
            }
            aria-hidden="true"
          >
            {TAG_ICON[tag]}
          </span>
        )}
        <span className="font-semibold text-slate-900 dark:text-white">
          {leg.ticker} {leg.strike} {leg.type === 'put' ? 'P' : 'C'}
        </span>
        <span className="text-sm text-slate-500 dark:text-slate-400">
          exp {leg.expiration} · {leg.dte} DTE
        </span>
      </div>
      <div className="mt-1 flex items-center gap-2">
        <span className="text-sm text-slate-600 dark:text-slate-300">
          {leg.decision_reason}
        </span>
        <span
          className={`inline-block px-2 py-0.5 text-xs rounded-full ${TAG_PILL[tag] || ''}`}
        >
          {TAG_LABEL[tag] || tag}
        </span>
      </div>
    </Link>
  );
}

export default function UpcomingExpirationsCard({ expirations, loading }) {
  if (loading) {
    return (
      <Card title="Upcoming expirations" description="Next 14 days" dataTestid="dashboard-expirations-card">
        <div className="space-y-3" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-12 animate-pulse rounded bg-slate-200 dark:bg-slate-700"
            />
          ))}
        </div>
      </Card>
    );
  }

  return (
    <Card
      title="Upcoming expirations"
      description="Next 14 days"
      dataTestid="dashboard-expirations-card"
      footer={
        <Link
          href="/journal"
          className="text-blue-600 dark:text-blue-400 hover:underline"
        >
          → Manage in Journal
        </Link>
      }
    >
      {expirations?.length ? (
        <div>
          {expirations.map((leg) => (
            <ExpirationRow key={leg.id} leg={leg} />
          ))}
        </div>
      ) : (
        <EmptyState
          title="Nothing expiring soon"
          description="No open option legs expiring in the next 14 days."
        />
      )}
    </Card>
  );
}
