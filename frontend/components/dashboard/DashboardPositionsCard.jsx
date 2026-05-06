import Link from 'next/link';
import Card from '../common/Card';
import EmptyState from '../common/EmptyState';
import { formatCurrency } from '../../utils/formatters';

function plClass(value) {
  if (value == null) return '';
  if (value > 0) return 'text-green-600 dark:text-green-400';
  if (value < 0) return 'text-red-600 dark:text-red-400';
  return '';
}

function PositionRow({ position }) {
  const cspOnly = (position.shares ?? 0) === 0;
  return (
    <tr
      data-testid="dashboard-position-row"
      className="border-b border-slate-100 dark:border-slate-700 last:border-b-0 hover:bg-slate-50 dark:hover:bg-slate-700/50"
    >
      <td className="py-2 px-3 font-semibold text-slate-900 dark:text-white">
        <Link
          href={`/journal?position=${encodeURIComponent(position.id)}`}
          className="hover:underline"
        >
          {position.ticker}
        </Link>
      </td>
      <td className="py-2 px-3 text-right tabular-nums text-slate-700 dark:text-slate-200">
        {cspOnly ? '—' : position.shares}
      </td>
      <td className="py-2 px-3 text-right tabular-nums text-slate-700 dark:text-slate-200">
        {cspOnly ? 'cash-secured' : formatCurrency(position.adjusted_cost_basis)}
      </td>
      <td className="py-2 px-3 text-right tabular-nums text-slate-700 dark:text-slate-200">
        {position.current_price == null ? '—' : formatCurrency(position.current_price)}
      </td>
      <td className="py-2 px-3 text-right tabular-nums text-slate-700 dark:text-slate-200">
        {position.notional == null ? '—' : formatCurrency(position.notional)}
      </td>
      <td className={`py-2 px-3 text-right tabular-nums ${plClass(position.unrealized_pl)}`}>
        {position.unrealized_pl == null
          ? '—'
          : `${position.unrealized_pl >= 0 ? '+' : ''}${formatCurrency(position.unrealized_pl)}`}
      </td>
      <td className="py-2 px-3 text-right tabular-nums text-slate-700 dark:text-slate-200">
        {position.open_legs_count}
      </td>
    </tr>
  );
}

export default function DashboardPositionsCard({ positions, loading }) {
  if (loading) {
    return (
      <Card title="Positions" dataTestid="dashboard-positions-card">
        <div className="space-y-2" aria-busy="true">
          {[0, 1, 2].map((i) => (
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
      title="Positions"
      dataTestid="dashboard-positions-card"
      footer={
        <Link
          href="/journal"
          className="text-blue-600 dark:text-blue-400 hover:underline"
        >
          → Open Journal
        </Link>
      }
    >
      {positions?.length ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-slate-500 dark:text-slate-400 uppercase">
                <th className="py-2 px-3 text-left">Ticker</th>
                <th className="py-2 px-3 text-right">Shares</th>
                <th className="py-2 px-3 text-right">Adj. basis</th>
                <th className="py-2 px-3 text-right">Current</th>
                <th className="py-2 px-3 text-right">Notional</th>
                <th className="py-2 px-3 text-right">P/L</th>
                <th className="py-2 px-3 text-right">Open legs</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((position) => (
                <PositionRow key={position.id} position={position} />
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState
          title="No positions yet"
          description="Import from Schwab or add a position manually."
          primaryAction={{ label: 'Open Journal', href: '/journal' }}
        />
      )}
    </Card>
  );
}
