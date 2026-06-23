import { useState, useEffect, useRef } from 'react';

const MODES = {
  API: 'api',
  CSV: 'csv',
};

// --- equity (issue #389) ---
const TYPE_LABELS = {
  sell_put: 'Sell Put',
  buy_put_close: 'Buy Put Close',
  assignment: 'Assignment',
  sell_call: 'Sell Call',
  buy_call_close: 'Buy Call Close',
  called_away: 'Called Away',
  buy_stock: 'Stock Buy',
  sell_stock: 'Stock Sell',
  dividend: 'Dividend',
};

const EQUITY_TYPES = new Set(['buy_stock', 'sell_stock', 'dividend']);

const EQUITY_PILL_CLASSES = {
  buy_stock: 'bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300',
  sell_stock: 'bg-violet-100 text-violet-800 dark:bg-violet-900/30 dark:text-violet-300',
  dividend: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300',
};

// Accessible "this column does not apply to this row kind" placeholder (#389).
function NotApplicable() {
  return (
    <span data-testid="na-placeholder" className="text-slate-400 dark:text-slate-500">
      <span aria-hidden="true">—</span>
      <span className="sr-only">Not applicable</span>
    </span>
  );
}

function toLocalDate(d) {
  const tzOffsetMs = d.getTimezoneOffset() * 60_000;
  return new Date(d.getTime() - tzOffsetMs).toISOString().slice(0, 10);
}

// Default lookback covers typical wheel/options cycles (~60-90 day expirations)
// without exceeding the server-side 365-day cap from issue #75.
const DEFAULT_LOOKBACK_DAYS = 90;
const MAX_LOOKBACK_DAYS = 365;
const MAX_CSV_BYTES = 5 * 1024 * 1024;

function defaultDates() {
  const end = new Date();
  const start = new Date();
  start.setDate(start.getDate() - DEFAULT_LOOKBACK_DAYS);
  return {
    startDate: toLocalDate(start),
    endDate: toLocalDate(end),
  };
}

export default function ImportModal({ onClose, onPreview, onImport, onPreviewCsv, onImportCsv, preview, loading }) {
  useEffect(() => {
    const handleKeyDown = (e) => {
      if (e.key === 'Escape' && !loading) onClose();
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, [onClose, loading]);

  const defaults = defaultDates();
  const [mode, setMode] = useState(MODES.API);
  const [startDate, setStartDate] = useState(defaults.startDate);
  const [endDate, setEndDate] = useState(defaults.endDate);
  const [csvFile, setCsvFile] = useState(null);
  const [csvError, setCsvError] = useState(null);
  const [result, setResult] = useState(null);
  const fileInputRef = useRef(null);
  const apiTabRef = useRef(null);
  const csvTabRef = useRef(null);

  const handlePreview = async () => {
    await onPreview(startDate, endDate);
  };

  const handleLookBack365 = async () => {
    const end = new Date();
    const start = new Date();
    start.setDate(start.getDate() - MAX_LOOKBACK_DAYS);
    const newStart = toLocalDate(start);
    const newEnd = toLocalDate(end);
    setStartDate(newStart);
    setEndDate(newEnd);
    await onPreview(newStart, newEnd);
  };

  const handleImport = async () => {
    let res = null;
    if (mode === MODES.CSV && csvFile && onImportCsv) {
      res = await onImportCsv(csvFile);
    } else {
      res = await onImport(startDate, endDate);
    }
    if (res) setResult(res);
  };

  const handleCsvChange = (e) => {
    const file = e.target.files?.[0] || null;
    setCsvError(null);
    if (!file) {
      setCsvFile(null);
      return;
    }
    if (!file.name.toLowerCase().endsWith('.csv')) {
      setCsvError('Only .csv files are accepted');
      setCsvFile(null);
      return;
    }
    if (file.size > MAX_CSV_BYTES) {
      setCsvError('CSV file is larger than the 5 MB limit');
      setCsvFile(null);
      return;
    }
    setCsvFile(file);
  };

  const handleCsvPreview = async () => {
    if (!csvFile || !onPreviewCsv) return;
    await onPreviewCsv(csvFile);
  };

  const handleSwitchMode = (next, { focus = false } = {}) => {
    if (next === mode) {
      if (focus) {
        const ref = next === MODES.API ? apiTabRef : csvTabRef;
        ref.current?.focus();
      }
      return;
    }
    setMode(next);
    setCsvError(null);
    setCsvFile(null);
    if (focus) {
      const ref = next === MODES.API ? apiTabRef : csvTabRef;
      ref.current?.focus();
    }
  };

  const handleTabKeyDown = (e) => {
    if (e.key !== 'ArrowLeft' && e.key !== 'ArrowRight') return;
    e.preventDefault();
    const next = mode === MODES.API ? MODES.CSV : MODES.API;
    handleSwitchMode(next, { focus: true });
  };

  const allDuplicates = preview && preview.new_count === 0;
  const emptyPreview = preview && preview.total === 0;

  const inputClass = 'w-full border border-slate-300 dark:border-slate-600 rounded-lg px-3 py-2 text-sm bg-white dark:bg-slate-700 text-slate-900 dark:text-white';
  const labelClass = 'block text-sm font-medium text-slate-700 dark:text-slate-300 mb-1';
  const tabBaseClass = 'px-3 py-1.5 text-sm font-medium rounded-lg border';
  const tabActiveClass = 'bg-blue-600 text-white border-blue-600';
  const tabInactiveClass = 'bg-white dark:bg-slate-700 text-slate-700 dark:text-slate-300 border-slate-300 dark:border-slate-600 hover:bg-slate-50 dark:hover:bg-slate-600';

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" data-testid="import-backdrop" aria-label="Close modal" onClick={loading ? undefined : onClose}>
      <div data-testid="import-modal" role="dialog" aria-modal="true" aria-labelledby="import-modal-title" className="bg-white dark:bg-slate-800 rounded-xl p-6 w-full max-w-2xl shadow-xl max-h-[80vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
        <h2 id="import-modal-title" className="text-lg font-semibold text-slate-900 dark:text-white mb-4">Import from Schwab</h2>

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
            {result.skipped_unmatched && result.skipped_unmatched.length > 0 && (
              <div
                data-testid="import-unmatched-warning"
                className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg p-4"
              >
                <p className="text-amber-800 dark:text-amber-200 font-medium">
                  Skipped {result.skipped_unmatched.length} unmatched{' '}
                  {result.skipped_unmatched.length === 1 ? 'sell' : 'sells'}
                </p>
                <p className="mt-1 text-sm text-amber-700 dark:text-amber-300">
                  These stock sells had no prior shares to draw on (
                  {[...new Set(result.skipped_unmatched.map((s) => s.ticker))].join(', ')}
                  ). Import the matching buys first, then re-import to capture them.
                </p>
              </div>
            )}
            <button onClick={onClose} className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700">
              Done
            </button>
          </div>
        ) : preview ? (
          <div data-testid="import-preview" className="space-y-4">
            <p className="text-sm text-slate-600 dark:text-slate-400">
              {preview.account_number ? `Account: ${preview.account_number} | ` : ''}
              {preview.total} trades found | {preview.duplicates} duplicates
              {preview.unmatched > 0 ? ` | ${preview.unmatched} unmatched` : ''} | {preview.new_count} new
            </p>

            {emptyPreview && mode === MODES.API && (
              <div
                data-testid="empty-preview-banner"
                className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg p-4 space-y-2"
              >
                <p className="text-sm text-amber-800 dark:text-amber-200">
                  No trades found between <span className="font-medium">{startDate}</span> and{' '}
                  <span className="font-medium">{endDate}</span>. Try a longer date range.
                </p>
                <button
                  data-testid="look-back-365-btn"
                  onClick={handleLookBack365}
                  disabled={loading}
                  className="px-3 py-1.5 bg-amber-600 text-white text-sm font-medium rounded-lg hover:bg-amber-700 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  {loading ? 'Loading...' : 'Look back 365 days'}
                </button>
              </div>
            )}

            {emptyPreview && mode === MODES.CSV && (
              <div
                data-testid="empty-csv-banner"
                className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-lg p-4"
              >
                <p className="text-sm text-amber-800 dark:text-amber-200">
                  No trades found in this CSV. Make sure the export is from
                  Schwab.com Activity & Statements.
                </p>
              </div>
            )}

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
                    {preview.trades.map((t, i) => {
                      const isEquity = EQUITY_TYPES.has(t.trade_type);
                      const isDividend = t.trade_type === 'dividend';
                      return (
                      <tr
                        key={i}
                        data-testid={isEquity ? 'equity-row' : undefined}
                        className="border-t border-slate-200 dark:border-slate-700"
                      >
                        <td className="px-3 py-2 text-slate-900 dark:text-white">{t.ticker}</td>
                        <td className="px-3 py-2 text-slate-700 dark:text-slate-300">
                          {isEquity ? (
                            <span
                              data-testid="row-type-badge"
                              className={`px-2 py-0.5 text-xs font-medium rounded-full ${EQUITY_PILL_CLASSES[t.trade_type]}`}
                            >
                              {TYPE_LABELS[t.trade_type] || t.trade_type}
                            </span>
                          ) : (
                            TYPE_LABELS[t.trade_type] || t.trade_type
                          )}
                        </td>
                        <td className="px-3 py-2 text-slate-700 dark:text-slate-300">
                          {isEquity ? <NotApplicable /> : `$${t.strike}`}
                        </td>
                        <td className="px-3 py-2 text-slate-700 dark:text-slate-300">
                          {isEquity ? <NotApplicable /> : t.expiration}
                        </td>
                        <td className="px-3 py-2 text-slate-700 dark:text-slate-300">
                          {isEquity ? (
                            <>
                              ${(t.unit_amount ?? 0).toFixed(2)}
                              {!isDividend && (
                                <span className="text-slate-400 dark:text-slate-500">/sh</span>
                              )}
                            </>
                          ) : (
                            `$${(t.premium ?? 0).toFixed(2)}`
                          )}
                        </td>
                        <td className="px-3 py-2 text-slate-700 dark:text-slate-300">
                          {isDividend ? <NotApplicable /> : t.quantity}
                        </td>
                        <td className="px-3 py-2">
                          {t.is_duplicate ? (
                            <span data-testid="duplicate-badge" className="px-2 py-0.5 text-xs font-medium rounded-full bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300">
                              Duplicate
                            </span>
                          ) : t.is_unmatched ? (
                            <span data-testid="unmatched-badge" title="No prior shares to draw on — will be skipped on import" className="px-2 py-0.5 text-xs font-medium rounded-full bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300">
                              Unmatched — will skip
                            </span>
                          ) : (
                            <span className="px-2 py-0.5 text-xs font-medium rounded-full bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300">
                              New
                            </span>
                          )}
                        </td>
                      </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}

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
            <div role="tablist" aria-label="Import source" data-testid="import-mode-toggle" className="flex gap-2" onKeyDown={handleTabKeyDown}>
              <button
                ref={apiTabRef}
                id="import-tab-api"
                role="tab"
                aria-selected={mode === MODES.API}
                aria-controls="import-panel-api"
                tabIndex={mode === MODES.API ? 0 : -1}
                data-testid="import-mode-api"
                onClick={() => handleSwitchMode(MODES.API)}
                className={`${tabBaseClass} ${mode === MODES.API ? tabActiveClass : tabInactiveClass}`}
              >
                Schwab API
              </button>
              <button
                ref={csvTabRef}
                id="import-tab-csv"
                role="tab"
                aria-selected={mode === MODES.CSV}
                aria-controls="import-panel-csv"
                tabIndex={mode === MODES.CSV ? 0 : -1}
                data-testid="import-mode-csv"
                onClick={() => handleSwitchMode(MODES.CSV)}
                className={`${tabBaseClass} ${mode === MODES.CSV ? tabActiveClass : tabInactiveClass}`}
              >
                CSV Upload
              </button>
            </div>

            {mode === MODES.API ? (
              <div id="import-panel-api" role="tabpanel" aria-labelledby="import-tab-api" tabIndex={0}>
                <div data-testid="import-api-fields" className="grid grid-cols-2 gap-4">
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
            ) : (
              <div id="import-panel-csv" role="tabpanel" aria-labelledby="import-tab-csv" tabIndex={0}>
                <div data-testid="import-csv-fields" className="space-y-2">
                  <label className={labelClass} htmlFor="csv-file-input">Schwab CSV export</label>
                  <input
                    id="csv-file-input"
                    ref={fileInputRef}
                    data-testid="csv-file-input"
                    type="file"
                    accept=".csv,text/csv"
                    onChange={handleCsvChange}
                    className="block text-sm text-slate-700 dark:text-slate-300 file:mr-3 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-sm file:font-medium file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 dark:file:bg-slate-700 dark:file:text-slate-300"
                  />
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Export from Schwab.com -&gt; Activity &amp; Statements -&gt; Transactions -&gt; Export. Maximum 5 MB.
                  </p>
                  {csvFile && (
                    <p data-testid="csv-file-name" className="text-xs text-slate-700 dark:text-slate-300">
                      Selected: {csvFile.name} ({Math.round(csvFile.size / 1024)} KB)
                    </p>
                  )}
                  {csvError && (
                    <p data-testid="csv-error" className="text-xs text-red-600 dark:text-red-400">
                      {csvError}
                    </p>
                  )}
                </div>
                <div className="flex gap-2">
                  <button
                    data-testid="preview-csv-btn"
                    onClick={handleCsvPreview}
                    disabled={loading || !csvFile}
                    className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
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
        )}
      </div>
    </div>
  );
}
