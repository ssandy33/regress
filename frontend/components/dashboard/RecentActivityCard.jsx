import Link from 'next/link';
import Card from '../common/Card';
import EmptyState from '../common/EmptyState';
import { formatRelativeTime } from '../../utils/formatters';

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

export default function RecentActivityCard({ events, loading }) {
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

  return (
    <Card title="Recent activity" dataTestid="dashboard-activity-card">
      {events?.length ? (
        <div>
          {events.map((event, i) => (
            <ActivityRow key={`${event.kind}-${event.timestamp}-${i}`} event={event} />
          ))}
        </div>
      ) : (
        <EmptyState
          title="No activity yet"
          description="Saved sessions, imports, and trades will appear here."
        />
      )}
    </Card>
  );
}
