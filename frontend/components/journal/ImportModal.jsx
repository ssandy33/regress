import { useState } from 'react';

const STRATEGIES = [
  { value: 'csp', label: 'Cash Secured Put' },
  { value: 'cc', label: 'Covered Call' },
  { value: 'wheel', label: 'Wheel' },
];

function defaultDates() {
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - 30);
  return {
    startDate: start.toISOString().split('T')[0],
    endDate: end.toISOString().split('T')[0],
  };
}

export default function ImportModal({ onClose, onPreview, onImport, preview, loading }) {
  const defaults = defaultDates();
  const [startDate, setStartDate] = useState(defaults.startDate);
  const [endDate, setEndDate] = useState(defaults.endDate);
  const [strategy, setStrategy] = useState('wheel');
  const [result, setResult] = useState(null);

  const handlePreview = async () => {
    await onPreview(startDate, endDate);
  };

  const handleImport = async () => {
    const res = await onImport(startDate, endDate, strategy);
    if (res) setResult(res);
  };

  const allDuplicates = preview && preview.new_count === 0;

  const inputClass = 'w-full border border-slate-300 dark:border-slate-600 rounded-lg px-3 py-2 text-sm bg-white dark:bg-slate-700 text-slate-900 dark:text-white';
  const labelClass = 'block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1';

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div data-testid="import-modal" className="bg-white dark:bg-slate-800 rounded-xl p-6 w-full max-w-2xl shadow-xl max-h-[80vh] overflow-y-auto">
        <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-4">Import from Schwab</h2>

        {result ? (
          <div data-testid="import-result" className="space-y-4">
            <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-lg p-4">
              <p className="text-green-800 dark:text-green-200 font-medium">Import complete</p>
              <ul className="mt-2 text-sm text-green-700 dark:text-green-300 space-y-1">
                <li>Imported: {result.imported} trades</li>
                <li>Skipped duplicates: {result.skipped_duplicates}</li>
                <li>Positions created: {result.positions_created}</li>
              </ul>
            </div>
            <button onClick={onClose} className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700">
              Done
            </button>
          </div>
        ) : preview ? (
          <div data-testid="import-preview" className="space-y-4">
            <p className="text-sm text-slate-600 dark:text-slate-400">
              Account: {preview.account_number} | {preview.total} trades found | {preview.duplicates} duplicates | {preview.new_count} new
            </p>

            {preview.trades.length > 0 && (
              <div className="border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
                <table className="w-full text-sm">
                  <thead className="bg-slate-50 dark:bg-slate-700">
                    <tr>
                      <th className="px-3 py-2 text-left text-slate-700 dark:text-slate-300">Ticker</th>
                      <th className="px-3 py-2 text-left text-slate-700 dark:text-slate-300">Type</th>
                      <th className="px-3 py-2 text-left text-slate-700 dark:text-slate-300">Strike</th>
                      <th className="px-3 py-2 text-left text-slate-700 dark:text-slate-300">Exp</th>
                      <th className="px-3 py-2 text-left text-slate-700 dark:text-slate-300">Premium</th>
                      <th className="px-3 py-2 text-left text-slate-700 dark:text-slate-300">Qty</th>
                      <th className="px-3 py-2 text-left text-slate-700 dark:text-slate-300">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {preview.trades.map((t, i) => (
                      <tr key={i} className="border-t border-slate-200 dark:border-slate-700">
                        <td className="px-3 py-2 text-slate-900 dark:text-white">{t.ticker}</td>
                        <td className="px-3 py-2 text-slate-700 dark:text-slate-300">{t.trade_type}</td>
                        <td className="px-3 py-2 text-slate-700 dark:text-slate-300">${t.strike}</td>
                        <td className="px-3 py-2 text-slate-700 dark:text-slate-300">{t.expiration}</td>
                        <td className="px-3 py-2 text-slate-700 dark:text-slate-300">${t.premium.toFixed(2)}</td>
                        <td className="px-3 py-2 text-slate-700 dark:text-slate-300">{t.quantity}</td>
                        <td className="px-3 py-2">
                          {t.is_duplicate ? (
                            <span data-testid="duplicate-badge" className="px-2 py-0.5 text-xs font-medium rounded-full bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300">
                              Duplicate
                            </span>
                          ) : (
                            <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300">
                              New
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}

            <div className="flex items-center gap-4">
              <div>
                <label className={labelClass}>Position Strategy</label>
                <select value={strategy} onChange={(e) => setStrategy(e.target.value)} className={inputClass}>
                  {STRATEGIES.map((s) => <option key={s.value} value={s.value}>{s.label}</option>)}
                </select>
              </div>
            </div>

            <div className="flex gap-2">
              <button
                data-testid="confirm-import-btn"
                onClick={handleImport}
                disabled={loading || allDuplicates}
                className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
              >
                {loading ? 'Importing...' : `Import ${preview.new_count} Trades`}
              </button>
              <button onClick={onClose} className="px-4 py-2 bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300 text-sm font-medium rounded-lg hover:bg-slate-300 dark:hover:bg-slate-600">
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className={labelClass}>Start Date</label>
                <input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className={inputClass} />
              </div>
              <div>
                <label className={labelClass}>End Date</label>
                <input type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} className={inputClass} />
              </div>
            </div>
            <div className="flex gap-2">
              <button
                data-testid="preview-import-btn"
                onClick={handlePreview}
                disabled={loading}
                className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50"
              >
                {loading ? 'Loading...' : 'Preview'}
              </button>
              <button onClick={onClose} className="px-4 py-2 bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300 text-sm font-medium rounded-lg hover:bg-slate-300 dark:hover:bg-slate-600">
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
