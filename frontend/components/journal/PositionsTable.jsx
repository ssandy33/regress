function formatCurrency(value) {
  if (value == null) return '--';
  return `$${Number(value).toFixed(2)}`;
}

function StatusBadge({ status }) {
  const isOpen = status === 'open';
  return (
    <span
      data-testid="status-badge"
      className={`inline-block px-2 py-0.5 text-xs font-medium rounded-full ${
        isOpen
          ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-300'
          : 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-400'
      }`}
    >
      {status}
    </span>
  );
}

export default function PositionsTable({ positions, loading, onSelectPosition, selectedPositionId }) {
  if (loading) {
    return (
      <div data-testid="positions-table" className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl p-6 animate-pulse space-y-3">
        {[...Array(3)].map((_, i) => (
          <div key={i} className="h-8 bg-slate-200 dark:bg-slate-700 rounded" />
        ))}
      </div>
    );
  }

  if (positions.length === 0) {
    return (
      <div data-testid="positions-table" className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl p-8 text-center text-slate-500 dark:text-slate-400">
        No positions yet
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden">
      <table data-testid="positions-table" className="w-full text-sm">
        <thead>
          <tr className="border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800">
            <th className="text-left px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Ticker</th>
            <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Shares</th>
            <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Broker Basis</th>
            <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Total Premiums</th>
            <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Adjusted Basis</th>
            <th className="text-right px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Min CC Strike</th>
            <th className="text-center px-4 py-3 font-medium text-slate-600 dark:text-slate-400">Status</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((pos) => (
            <tr
              key={pos.id}
              data-testid="position-row"
              onClick={() => onSelectPosition(pos.id)}
              className={`border-b border-slate-100 dark:border-slate-700 cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-700/50 transition-colors ${
                selectedPositionId === pos.id ? 'bg-blue-50 dark:bg-blue-900/20' : ''
              }`}
            >
              <td className="px-4 py-3 font-medium text-slate-900 dark:text-white">{pos.ticker}</td>
              <td className="px-4 py-3 text-right text-slate-700 dark:text-slate-300">{pos.shares}</td>
              <td className="px-4 py-3 text-right text-slate-700 dark:text-slate-300">{formatCurrency(pos.broker_cost_basis)}</td>
              <td className="px-4 py-3 text-right text-slate-700 dark:text-slate-300">{formatCurrency(pos.total_premiums)}</td>
              <td className="px-4 py-3 text-right text-slate-700 dark:text-slate-300">{formatCurrency(pos.adjusted_cost_basis)}</td>
              <td className="px-4 py-3 text-right text-slate-700 dark:text-slate-300">{formatCurrency(pos.min_compliant_cc_strike)}</td>
              <td className="px-4 py-3 text-center"><StatusBadge status={pos.status} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
