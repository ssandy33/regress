import { useEffect } from 'react';

/**
 * Reusable confirmation modal used by destructive journal actions
 * (delete position, delete trade). Mirrors the overlay/ESC + backdrop-close
 * pattern from `PositionForm` and `ImportModal` (PR #76).
 *
 * Props:
 *   - title: heading shown at the top of the dialog.
 *   - message: ReactNode body explaining the consequence of confirming.
 *   - confirmLabel / cancelLabel: button text overrides.
 *   - confirmVariant: "danger" (default, red) | "primary" (blue).
 *   - busy: when true, disables the buttons and swaps the confirm label.
 *   - onConfirm: invoked when the user confirms.
 *   - onCancel: invoked on Cancel button, ESC key, or backdrop click.
 */
export default function ConfirmDialog({
  title,
  message,
  confirmLabel = 'Delete',
  cancelLabel = 'Cancel',
  confirmVariant = 'danger',
  busy = false,
  onConfirm,
  onCancel,
}) {
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && !busy) onCancel();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onCancel, busy]);

  const confirmClass =
    confirmVariant === 'danger'
      ? 'px-4 py-2 bg-red-600 text-white text-sm font-medium rounded-lg hover:bg-red-700 disabled:bg-red-400'
      : 'px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:bg-blue-400';

  return (
    <div
      data-testid="confirm-dialog-backdrop"
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50"
      onClick={() => {
        if (!busy) onCancel();
      }}
    >
      <div
        data-testid="confirm-dialog"
        role="dialog"
        aria-modal="true"
        className="bg-white dark:bg-slate-800 rounded-xl p-6 w-full max-w-md space-y-4 shadow-xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-slate-900 dark:text-white">{title}</h2>
        <div className="text-sm text-slate-600 dark:text-slate-300">{message}</div>
        <div className="flex gap-2 pt-2 justify-end">
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="px-4 py-2 bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300 text-sm font-medium rounded-lg hover:bg-slate-300 dark:hover:bg-slate-600 disabled:opacity-50"
          >
            {cancelLabel}
          </button>
          <button
            type="button"
            data-testid="confirm-dialog-confirm"
            onClick={onConfirm}
            disabled={busy}
            className={confirmClass}
          >
            {busy ? 'Working...' : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}
