import { useState } from 'react';
import toast from 'react-hot-toast';
import { clearAllJournal } from '../../api/client';

const REQUIRED_TOKEN = 'DELETE';

/**
 * Settings → Danger Zone disclosure for destructive cross-cutting actions.
 *
 * v1 ships a single action: "Clear All Journal Data" (wipe every position +
 * trade). The disclosure is collapsed by default; opening it reveals an
 * input that requires the user to type the exact uppercase string `DELETE`
 * before the confirm button enables. Closing the panel resets the typed
 * value so it never persists across re-opens.
 */
export default function DangerZone() {
  const [open, setOpen] = useState(false);
  const [confirmText, setConfirmText] = useState('');
  const [busy, setBusy] = useState(false);

  const armed = confirmText === REQUIRED_TOKEN;

  const handleToggle = () => {
    setOpen((prev) => {
      if (prev) {
        // Reset state on collapse so a stale typed token never lingers.
        setConfirmText('');
      }
      return !prev;
    });
  };

  const handleClear = async () => {
    if (!armed || busy) return;
    setBusy(true);
    try {
      const result = await clearAllJournal();
      const positions = result?.deleted_positions ?? 0;
      const trades = result?.deleted_trades ?? 0;
      toast.success(`Deleted ${positions} positions, ${trades} trades`);
      setConfirmText('');
      setOpen(false);
    } catch {
      toast.error('Failed to clear journal data');
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      data-testid="danger-zone"
      className="bg-red-50 dark:bg-red-900/10 rounded-xl p-6 border border-red-200 dark:border-red-800"
    >
      <button
        type="button"
        data-testid="danger-zone-toggle"
        onClick={handleToggle}
        aria-expanded={open}
        className="w-full flex items-center justify-between text-left"
      >
        <div>
          <h2 className="text-lg font-semibold text-red-700 dark:text-red-300">Danger Zone</h2>
          <p className="text-sm text-red-600/80 dark:text-red-300/80">
            Irreversible actions. Restore from a Database Backup if you regret one.
          </p>
        </div>
        <span className="text-red-600 dark:text-red-300 text-sm font-medium">
          {open ? 'Hide' : 'Show'}
        </span>
      </button>

      {open && (
        <div className="mt-4 bg-white dark:bg-slate-800 rounded-lg border border-red-200 dark:border-red-800 p-4 space-y-3">
          <div>
            <h3 className="text-sm font-semibold text-slate-900 dark:text-white">
              Clear All Journal Data
            </h3>
            <p className="text-sm text-slate-600 dark:text-slate-400">
              Permanently deletes every position and trade. This cannot be undone.
              Use the Database Backups section above to recover if you change your mind.
            </p>
          </div>

          <label className="block text-sm text-slate-700 dark:text-slate-300">
            Type <code className="bg-slate-100 dark:bg-slate-700 px-1 rounded">DELETE</code> to enable the button:
            <input
              type="text"
              data-testid="danger-zone-confirm-input"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              className="mt-1 w-full px-3 py-2 text-sm border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-red-500"
              autoComplete="off"
              spellCheck="false"
            />
          </label>

          <button
            type="button"
            data-testid="clear-journal-btn"
            onClick={handleClear}
            disabled={!armed || busy}
            className="px-4 py-2 text-sm bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:bg-red-300 dark:disabled:bg-red-900/50 disabled:cursor-not-allowed"
          >
            {busy ? 'Clearing...' : 'Clear All Journal Data'}
          </button>
        </div>
      )}
    </section>
  );
}
