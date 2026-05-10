import { useState } from 'react';
import ConfirmDialog from '../common/ConfirmDialog';

/**
 * Settings → Reconcile journal section (issue #139).
 *
 * Re-derives every position's lifecycle state (status / shares / basis /
 * strategy / closed_at) from its trade ledger by walking
 * ``recompute_position_state`` for every row. This is the in-app escape
 * hatch for journals whose stored derived state has drifted from the
 * ledger (e.g., imported pre-#127 / pre-#131 / pre-#136 fixes) and is the
 * non-destructive counterpart to the Danger Zone clear-all.
 *
 * The Preview button issues a ``dry_run=true`` request and renders the
 * per-position before/after diff inline below the buttons. Apply opens a
 * ``ConfirmDialog`` (no type-DELETE gate — the operation is non-destructive
 * and idempotent) and on confirm issues ``dry_run=false``; the parent hook
 * surfaces the success toast.
 *
 * Both buttons remain enabled independently — Apply does not require a
 * prior Preview run. When ``positionCount === 0`` (empty journal) the
 * empty-state copy renders and both buttons are disabled.
 */
export default function ReconcileJournal({
  previewReconcile,
  applyReconcile,
  positionCount,
}) {
  const [preview, setPreview] = useState(null);
  const [previewing, setPreviewing] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [applying, setApplying] = useState(false);

  const isEmpty = positionCount === 0;

  const handlePreview = async () => {
    if (previewing || isEmpty) return;
    setPreviewing(true);
    try {
      const result = await previewReconcile();
      setPreview(result);
    } finally {
      setPreviewing(false);
    }
  };

  const handleApplyClick = () => {
    if (applying || isEmpty) return;
    setConfirmOpen(true);
  };

  const handleApplyConfirm = async () => {
    if (applying) return;
    setApplying(true);
    try {
      const result = await applyReconcile();
      if (result) {
        // Refresh the inline preview with the post-apply diff so the user
        // sees the realised changes (each row's before/after now reflects
        // the persisted state).
        setPreview(result);
        setConfirmOpen(false);
      }
    } finally {
      setApplying(false);
    }
  };

  const handleApplyCancel = () => {
    if (applying) return;
    setConfirmOpen(false);
  };

  return (
    <section
      data-testid="reconcile-journal"
      className="bg-slate-50 dark:bg-slate-800 rounded-xl p-6 border border-slate-200 dark:border-slate-700"
    >
      <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-1">
        Reconcile journal
      </h2>
      <p className="text-sm text-slate-500 dark:text-slate-400 mb-4">
        Re-derive every position&apos;s state (status, shares, cost basis,
        strategy) from its trade ledger. Non-destructive — Preview shows what
        would change without writing anything.
      </p>

      {isEmpty ? (
        <p
          data-testid="reconcile-empty-state"
          className="text-sm text-slate-400 dark:text-slate-500"
        >
          No positions to reconcile.
        </p>
      ) : null}

      <div className="flex gap-2">
        <button
          type="button"
          data-testid="reconcile-preview-btn"
          onClick={handlePreview}
          disabled={previewing || isEmpty}
          className="px-4 py-2 text-sm border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-700 disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {previewing ? 'Previewing...' : 'Preview'}
        </button>
        <button
          type="button"
          data-testid="reconcile-apply-btn"
          onClick={handleApplyClick}
          disabled={applying || isEmpty}
          className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-blue-400 disabled:cursor-not-allowed"
        >
          {applying ? 'Applying...' : 'Apply'}
        </button>
      </div>

      {preview && (
        <div className="mt-4" data-testid="reconcile-result">
          <div className="text-xs text-slate-500 dark:text-slate-400 mb-2">
            {preview.dry_run ? 'Preview' : 'Applied'} —
            {' '}{preview.positions_processed} processed,
            {' '}{preview.status_changes} status changes,
            {' '}{preview.share_corrections} share corrections,
            {' '}{preview.basis_corrections} basis corrections,
            {' '}{preview.trades_stamped} trade closed_at values stamped
            {preview.errors > 0 ? `, ${preview.errors} errors` : ''}
          </div>
          {preview.per_position && preview.per_position.length > 0 ? (
            <div className="overflow-x-auto">
              <table
                data-testid="reconcile-table"
                className="w-full text-xs"
              >
                <thead>
                  <tr className="border-b border-slate-200 dark:border-slate-700">
                    <th className="text-left px-2 py-1 font-medium text-slate-500 dark:text-slate-400">
                      Ticker
                    </th>
                    <th className="text-left px-2 py-1 font-medium text-slate-500 dark:text-slate-400">
                      Status
                    </th>
                    <th className="text-right px-2 py-1 font-medium text-slate-500 dark:text-slate-400">
                      Shares
                    </th>
                    <th className="text-right px-2 py-1 font-medium text-slate-500 dark:text-slate-400">
                      Basis
                    </th>
                    <th className="text-left px-2 py-1 font-medium text-slate-500 dark:text-slate-400">
                      Strategy
                    </th>
                    <th className="text-right px-2 py-1 font-medium text-slate-500 dark:text-slate-400">
                      Legs consumed
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {preview.per_position.map((row) => (
                    <tr
                      key={row.ticker}
                      data-testid="reconcile-row"
                      className="border-b border-slate-100 dark:border-slate-700/50"
                    >
                      <td className="px-2 py-1 font-medium text-slate-900 dark:text-white">
                        {row.ticker}
                      </td>
                      <td className="px-2 py-1 text-slate-600 dark:text-slate-400">
                        {row.status_before} → {row.status_after}
                      </td>
                      <td className="px-2 py-1 text-right text-slate-600 dark:text-slate-400">
                        {row.shares_before} → {row.shares_after}
                      </td>
                      <td className="px-2 py-1 text-right text-slate-600 dark:text-slate-400">
                        ${row.basis_before.toFixed(2)} → ${row.basis_after.toFixed(2)}
                      </td>
                      <td className="px-2 py-1 text-slate-600 dark:text-slate-400">
                        {row.strategy_before} → {row.strategy_after}
                      </td>
                      <td className="px-2 py-1 text-right text-slate-600 dark:text-slate-400">
                        {row.legs_consumed}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <p className="text-xs text-slate-400 dark:text-slate-500">
              No changes detected.
            </p>
          )}
        </div>
      )}

      {confirmOpen && (
        <ConfirmDialog
          title="Reconcile journal"
          message={`Reconcile ${positionCount} position${positionCount === 1 ? '' : 's'}? This will recompute position state from the trade ledger.`}
          confirmLabel="Reconcile"
          confirmVariant="primary"
          busy={applying}
          onConfirm={handleApplyConfirm}
          onCancel={handleApplyCancel}
        />
      )}
    </section>
  );
}
