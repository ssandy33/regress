import { useEffect, useRef, useState } from 'react';
import TradeEntryForm from './TradeEntryForm';
import ConfirmDialog from '../common/ConfirmDialog';

const TYPE_LABELS = {
  sell_put: 'Sell Put',
  buy_put_close: 'Buy Put Close',
  assignment: 'Assignment',
  sell_call: 'Sell Call',
  buy_call_close: 'Buy Call Close',
  called_away: 'Called Away',
};

const REASON_LABELS = {
  fifty_pct_target: '50% Target',
  full_expiration: 'Full Expiry',
  rolled: 'Rolled',
  closed_early: 'Closed Early',
  assigned: 'Assigned',
  called_away: 'Called Away',
};

const STRATEGY_LABELS = { csp: 'CSP', cc: 'CC', wheel: 'Wheel' };

function formatCurrency(value) {
  if (value == null) return '--';
  return `$${Number(value).toFixed(2)}`;
}

export default function TradeHistory({
  position,
  onAddTrade,
  onDeleteTrade,
  closeLegPrefill,
}) {
  const [showForm, setShowForm] = useState(false);
  const [pendingDeleteTradeId, setPendingDeleteTradeId] = useState(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  // `closeLegPrefill` (issue #244) — when the journal page resolves a
  // buy-to-close deep-link, it passes a pre-fill object. Auto-open the trade
  // form seeded with it, once, when it first becomes available.
  const appliedPrefillRef = useRef(false);
  // Tracks whether the currently-visible form is the auto-opened, prefilled
  // instance. The prefill seeds *only* that first form — a later manual
  // "Add Trade" must open a blank form, not reuse the stale buy-to-close leg.
  const [formIsPrefilled, setFormIsPrefilled] = useState(false);

  useEffect(() => {
    if (closeLegPrefill && !appliedPrefillRef.current) {
      appliedPrefillRef.current = true;
      setFormIsPrefilled(true);
      setShowForm(true);
    }
  }, [closeLegPrefill]);

  const toggleForm = () => {
    setShowForm((prev) => {
      const next = !prev;
      // Any manual open/close drops the prefill — it belongs to the auto-open.
      if (formIsPrefilled) setFormIsPrefilled(false);
      return next;
    });
  };

  const closeForm = () => {
    setShowForm(false);
    if (formIsPrefilled) setFormIsPrefilled(false);
  };

  const handleAddTrade = async (data) => {
    try {
      await onAddTrade(data);
      closeForm();
    } catch {
      // Form stays open for retry; error toast handled by parent
    }
  };

  const pendingDeleteTrade = pendingDeleteTradeId
    ? (position.trades || []).find((t) => t.id === pendingDeleteTradeId) || null
    : null;

  const handleConfirmDeleteTrade = async () => {
    if (!pendingDeleteTradeId) return;
    setDeleteBusy(true);
    try {
      await onDeleteTrade(pendingDeleteTradeId);
      setPendingDeleteTradeId(null);
    } finally {
      setDeleteBusy(false);
    }
  };

  return (
    <div data-testid="trade-history" className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h2 className="text-lg font-semibold text-slate-900 dark:text-white">{position.ticker}</h2>
          <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-300">
            {STRATEGY_LABELS[position.strategy] || position.strategy}
          </span>
          <span className="text-sm text-slate-500 dark:text-slate-400">
            Adjusted Basis: {formatCurrency(position.adjusted_cost_basis)} | Min CC Strike: {formatCurrency(position.min_compliant_cc_strike)}
          </span>
        </div>
        <button
          data-testid="add-trade-btn"
          onClick={toggleForm}
          className="px-3 py-1.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700"
        >
          {showForm ? 'Cancel' : 'Add Trade'}
        </button>
      </div>

      {showForm && (
        <div className="p-4 border-b border-slate-200 dark:border-slate-700">
          <TradeEntryForm
            positionId={position.id}
            initialValues={formIsPrefilled ? closeLegPrefill : undefined}
            onSubmit={handleAddTrade}
            onCancel={closeForm}
          />
        </div>
      )}

      {(!position.trades || position.trades.length === 0) ? (
        <div className="p-6 text-center text-slate-500 dark:text-slate-400">No trades yet</div>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800">
              <th className="text-left px-4 py-2 font-medium text-slate-600 dark:text-slate-400">Date</th>
              <th className="text-left px-4 py-2 font-medium text-slate-600 dark:text-slate-400">Type</th>
              <th className="text-right px-4 py-2 font-medium text-slate-600 dark:text-slate-400">Strike</th>
              <th className="text-left px-4 py-2 font-medium text-slate-600 dark:text-slate-400">Expiration</th>
              <th className="text-right px-4 py-2 font-medium text-slate-600 dark:text-slate-400">Premium</th>
              <th className="text-right px-4 py-2 font-medium text-slate-600 dark:text-slate-400">Fees</th>
              <th className="text-right px-4 py-2 font-medium text-slate-600 dark:text-slate-400">Qty</th>
              <th className="text-left px-4 py-2 font-medium text-slate-600 dark:text-slate-400">Close Reason</th>
              <th className="px-4 py-2" />
            </tr>
          </thead>
          <tbody>
            {(position.trades || []).map((t) => (
              <tr key={t.id} data-testid="trade-row" className="border-b border-slate-100 dark:border-slate-700">
                <td className="px-4 py-2 text-slate-700 dark:text-slate-300">{t.opened_at?.split('T')[0]}</td>
                <td className="px-4 py-2 text-slate-700 dark:text-slate-300">{TYPE_LABELS[t.trade_type] || t.trade_type}</td>
                <td className="px-4 py-2 text-right text-slate-700 dark:text-slate-300">{formatCurrency(t.strike)}</td>
                <td className="px-4 py-2 text-slate-700 dark:text-slate-300">{t.expiration}</td>
                <td className="px-4 py-2 text-right text-slate-700 dark:text-slate-300">{formatCurrency(t.premium)}</td>
                <td className="px-4 py-2 text-right text-slate-700 dark:text-slate-300">{formatCurrency(t.fees)}</td>
                <td className="px-4 py-2 text-right text-slate-700 dark:text-slate-300">{t.quantity}</td>
                <td className="px-4 py-2 text-slate-500 dark:text-slate-400">{REASON_LABELS[t.close_reason] || '--'}</td>
                <td className="px-4 py-2">
                  <button
                    data-testid="trade-delete-btn"
                    onClick={() => setPendingDeleteTradeId(t.id)}
                    className="text-red-500 hover:text-red-700 text-xs font-medium"
                  >
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {pendingDeleteTradeId && (
        <ConfirmDialog
          title="Delete trade?"
          message={
            pendingDeleteTrade ? (
              <p>
                Delete this{' '}
                <strong>
                  {TYPE_LABELS[pendingDeleteTrade.trade_type] || pendingDeleteTrade.trade_type}
                </strong>{' '}
                at strike {formatCurrency(pendingDeleteTrade.strike)} on{' '}
                {pendingDeleteTrade.expiration}? The position and its other trades remain
                intact.
              </p>
            ) : (
              <p>Delete this trade? The position and its other trades remain intact.</p>
            )
          }
          confirmLabel="Delete"
          busy={deleteBusy}
          onConfirm={handleConfirmDeleteTrade}
          onCancel={() => {
            if (!deleteBusy) setPendingDeleteTradeId(null);
          }}
        />
      )}
    </div>
  );
}
