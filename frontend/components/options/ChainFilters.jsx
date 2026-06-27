import { useState } from 'react';

export default function ChainFilters({
  ticker, setTicker,
  strategy, setStrategy,
  costBasis, setCostBasis,
  sharesHeld, setSharesHeld,
  capitalAvailable, setCapitalAvailable,
  minDte, setMinDte,
  maxDte, setMaxDte,
  returnTarget, setReturnTarget,
  callDistance, setCallDistance,
  minDelta, setMinDelta,
  maxDelta, setMaxDelta,
  earningsBuffer, setEarningsBuffer,
  onScan, loading,
  onReset,
  schwabAvailable = true,
  schwabLoading = false,
}) {
  const [collapsed, setCollapsed] = useState(false);

  if (collapsed) {
    return (
      <div className="w-12 border-r border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 flex flex-col items-center pt-3">
        <button
          onClick={() => setCollapsed(false)}
          className="p-2 rounded hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300"
          aria-label="Expand filters"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 5l7 7-7 7M5 5l7 7-7 7" />
          </svg>
        </button>
      </div>
    );
  }

  const inputClass = "w-full px-3 py-2 text-sm border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-blue-500 focus:outline-none";
  const labelClass = "block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1.5";

  return (
    <aside className="w-80 border-r border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 flex flex-col shrink-0 overflow-y-auto">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-slate-700">
        <span className="text-sm font-medium text-slate-700 dark:text-slate-200">Option Scanner</span>
        <button
          onClick={() => setCollapsed(true)}
          className="p-1 rounded hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-500 dark:text-slate-400"
          aria-label="Collapse sidebar"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
          </svg>
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {/* Asset Section */}
        <div className="p-4 space-y-4">
          <h2 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">Asset</h2>
          <div>
            <label htmlFor="scanner-ticker" className={labelClass}>Ticker Symbol</label>
            <input
              id="scanner-ticker"
              name="scanner-ticker"
              type="text"
              value={ticker}
              onChange={(e) => setTicker(e.target.value.toUpperCase())}
              onKeyDown={(e) => e.key === 'Enter' && onScan()}
              placeholder="SOFI, AAPL, F..."
              className={inputClass}
            />
          </div>
        </div>

        {/* Strategy Section */}
        <div className="pt-4 p-4 space-y-4 border-t border-slate-200 dark:border-slate-700">
          <h2 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">Strategy</h2>
          <div>
            {/* Not a native form control — the strategy picker is a button
                toggle group, so this is a labelling <span>, not a <label>,
                and the group is named via aria-labelledby. (#410) */}
            <span id="scanner-strategy-label" className={labelClass}>Strategy</span>
            <div role="group" aria-labelledby="scanner-strategy-label" className="flex rounded-lg border border-slate-300 dark:border-slate-600 overflow-hidden">
              <button
                onClick={() => setStrategy('cash_secured_put')}
                className={`flex-1 py-2 text-xs font-medium transition-colors ${
                  strategy === 'cash_secured_put'
                    ? 'bg-blue-600 text-white'
                    : 'bg-white dark:bg-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-600'
                }`}
              >
                Cash-Secured Put
              </button>
              <button
                onClick={() => setStrategy('covered_call')}
                className={`flex-1 py-2 text-xs font-medium transition-colors ${
                  strategy === 'covered_call'
                    ? 'bg-blue-600 text-white'
                    : 'bg-white dark:bg-slate-700 text-slate-600 dark:text-slate-300 hover:bg-slate-50 dark:hover:bg-slate-600'
                }`}
              >
                Covered Call
              </button>
            </div>
          </div>

          {/* Covered Call Fields */}
          {strategy === 'covered_call' && (
            <>
              <div>
                <label htmlFor="scanner-cost-basis" className={labelClass}>Cost Basis ($)</label>
                <input
                  id="scanner-cost-basis"
                  name="scanner-cost-basis"
                  type="number"
                  step="0.01"
                  value={costBasis}
                  onChange={(e) => setCostBasis(e.target.value)}
                  placeholder="15.50"
                  className={inputClass}
                />
              </div>
              <div>
                <label htmlFor="scanner-shares-held" className={labelClass}>Shares Held</label>
                <input
                  id="scanner-shares-held"
                  name="scanner-shares-held"
                  type="number"
                  step="100"
                  value={sharesHeld}
                  onChange={(e) => setSharesHeld(parseInt(e.target.value) || 100)}
                  className={inputClass}
                  data-testid="scanner-shares-held-input"
                />
              </div>
              <div>
                <label htmlFor="scanner-call-distance" className={labelClass}>Min Call Distance % (10% Rule)</label>
                <input
                  id="scanner-call-distance"
                  name="scanner-call-distance"
                  type="number"
                  step="0.5"
                  value={callDistance}
                  onChange={(e) => setCallDistance(parseFloat(e.target.value) || 10)}
                  className={inputClass}
                />
              </div>
            </>
          )}

          {/* CSP Fields */}
          {strategy === 'cash_secured_put' && (
            <div>
              <label htmlFor="scanner-capital" className={labelClass}>Capital Available ($)</label>
              <input
                id="scanner-capital"
                name="scanner-capital"
                type="number"
                step="100"
                value={capitalAvailable}
                onChange={(e) => setCapitalAvailable(e.target.value)}
                placeholder="5000"
                className={inputClass}
              />
            </div>
          )}
        </div>

        {/* Filters Section */}
        <div className="pt-4 p-4 space-y-4 border-t border-slate-200 dark:border-slate-700">
          <h2 className="text-[11px] font-semibold uppercase tracking-wider text-slate-400 dark:text-slate-500">Filters</h2>

          {/* DTE Range */}
          <div>
            <label htmlFor="scanner-dte-min" className={labelClass}>DTE Range (days)</label>
            <div className="flex gap-2 items-center">
              <input
                id="scanner-dte-min"
                name="scanner-dte-min"
                type="number"
                value={minDte}
                onChange={(e) => setMinDte(parseInt(e.target.value) || 0)}
                className={`${inputClass} w-20 text-center`}
                aria-label="DTE Range minimum (days)"
              />
              <span className="text-xs text-slate-400">to</span>
              <input
                id="scanner-dte-max"
                name="scanner-dte-max"
                type="number"
                value={maxDte}
                onChange={(e) => setMaxDte(parseInt(e.target.value) || 0)}
                className={`${inputClass} w-20 text-center`}
                aria-label="DTE Range maximum (days)"
              />
            </div>
          </div>

          {/* Monthly Return Target */}
          <div>
            <label htmlFor="scanner-return-target" className={labelClass}>Monthly Return Target (%)</label>
            <input
              id="scanner-return-target"
              name="scanner-return-target"
              type="number"
              step="0.1"
              value={returnTarget}
              onChange={(e) => setReturnTarget(parseFloat(e.target.value) || 0)}
              className={inputClass}
            />
          </div>

          {/* Delta Range */}
          <div>
            <label htmlFor="scanner-delta-min" className={labelClass}>Delta Range</label>
            <div className="flex gap-2 items-center">
              <input
                id="scanner-delta-min"
                name="scanner-delta-min"
                type="number"
                step="0.01"
                value={minDelta}
                onChange={(e) => setMinDelta(parseFloat(e.target.value) || 0)}
                className={`${inputClass} w-20 text-center`}
                aria-label="Delta Range minimum"
              />
              <span className="text-xs text-slate-400">to</span>
              <input
                id="scanner-delta-max"
                name="scanner-delta-max"
                type="number"
                step="0.01"
                value={maxDelta}
                onChange={(e) => setMaxDelta(parseFloat(e.target.value) || 0)}
                className={`${inputClass} w-20 text-center`}
                aria-label="Delta Range maximum"
              />
            </div>
          </div>

          {/* Earnings Buffer */}
          <div>
            <label htmlFor="scanner-earnings-buffer" className={labelClass}>Earnings Buffer (days)</label>
            <input
              id="scanner-earnings-buffer"
              name="scanner-earnings-buffer"
              type="number"
              value={earningsBuffer}
              onChange={(e) => setEarningsBuffer(parseInt(e.target.value) || 0)}
              className={inputClass}
            />
          </div>
        </div>
      </div>

      {/* Action Buttons */}
      <div className="p-4 border-t border-slate-200 dark:border-slate-700 space-y-2">
        <button
          onClick={onScan}
          disabled={loading || (!schwabLoading && !schwabAvailable)}
          title={!schwabLoading && !schwabAvailable ? 'Schwab API is not configured. Visit Settings to connect.' : undefined}
          className="w-full py-2 px-4 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 disabled:cursor-not-allowed text-white rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2"
        >
          {loading ? (
            <>
              <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Scanning...
            </>
          ) : (
            'Scan Options'
          )}
        </button>
        <button
          onClick={onReset}
          className="w-full py-2 px-4 border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-200 rounded-lg text-sm font-medium hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
        >
          Reset
        </button>
      </div>
    </aside>
  );
}
