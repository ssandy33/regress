import { useEffect, useRef, useState } from 'react';

function formatCurrency(value) {
  if (value == null) return '--';
  return `$${Number(value).toFixed(2)}`;
}

/**
 * Per-share basis cell (issue #320). Renders the per-share value with a muted
 * non-tabular `/sh` affordance so it can't be misread as a total. The currency
 * number keeps `tabular-nums` so digits align with the other right-aligned
 * columns. `value == null` (shares === 0, backend sends null) renders an
 * em-dash — never `$0.00` / Infinity.
 */
function PerShareBasis({ value, testid }) {
  if (value == null) {
    return (
      <span data-testid={testid} className="text-slate-400 dark:text-slate-500">
        —
      </span>
    );
  }
  return (
    <span data-testid={testid}>
      <span className="tabular-nums">{formatCurrency(value)}</span>
      <span className="text-xs text-slate-400 dark:text-slate-500 ml-1">/sh</span>
    </span>
  );
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

/**
 * Single-item kebab actions menu per row. Designed so future actions can be
 * appended without restructuring — v1 ships only `Delete`.
 *
 * Stops click propagation so opening the menu / clicking an action never
 * triggers the outer row `onSelectPosition` handler.
 */
function RowActionsMenu({ positionId, ticker, onDelete }) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const handleDocClick = (e) => {
      if (containerRef.current && !containerRef.current.contains(e.target)) {
        setOpen(false);
      }
    };
    const handleKey = (e) => {
      if (e.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', handleDocClick);
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('mousedown', handleDocClick);
      document.removeEventListener('keydown', handleKey);
    };
  }, [open]);

  return (
    <div ref={containerRef} className="relative inline-block text-left">
      <button
        type="button"
        data-testid="position-actions-btn"
        aria-label={`Actions for ${ticker}`}
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className="px-2 py-1 text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700 rounded"
      >
        <span aria-hidden>&hellip;</span>
      </button>
      {open && (
        <div
          role="menu"
          data-testid="position-actions-menu"
          className="absolute right-0 z-10 mt-1 w-32 origin-top-right rounded-md bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 shadow-lg"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            role="menuitem"
            data-testid="position-delete-btn"
            onClick={(e) => {
              e.stopPropagation();
              setOpen(false);
              onDelete(positionId);
            }}
            className="block w-full text-left px-3 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-md"
          >
            Delete
          </button>
        </div>
      )}
    </div>
  );
}

export default function PositionsTable({
  positions,
  loading,
  onSelectPosition,
  selectedPositionId,
  onDeletePosition,
}) {
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
            <th className="px-4 py-3" aria-label="Actions" />
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
              <td className="px-4 py-3 text-right text-slate-700 dark:text-slate-300">
                <PerShareBasis
                  value={pos.broker_cost_basis_per_share}
                  testid="position-broker-basis-per-share"
                />
              </td>
              <td className="px-4 py-3 text-right text-slate-700 dark:text-slate-300">{formatCurrency(pos.total_premiums)}</td>
              <td className="px-4 py-3 text-right text-slate-700 dark:text-slate-300">
                <PerShareBasis
                  value={pos.adjusted_cost_basis_per_share}
                  testid="position-adjusted-basis-per-share"
                />
              </td>
              <td className="px-4 py-3 text-right text-slate-700 dark:text-slate-300">{formatCurrency(pos.min_compliant_cc_strike)}</td>
              <td className="px-4 py-3 text-center"><StatusBadge status={pos.status} /></td>
              <td className="px-4 py-3 text-right">
                {onDeletePosition && (
                  <RowActionsMenu
                    positionId={pos.id}
                    ticker={pos.ticker}
                    onDelete={onDeletePosition}
                  />
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
