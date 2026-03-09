import { useOptionScanner } from '../../hooks/useOptionScanner';
import { useSchwabStatus } from '../../hooks/useSchwabStatus';
import ChainFilters from './ChainFilters';
import StrikeTable from './StrikeTable';
import RiskRewardPanel from './RiskRewardPanel';
import Header from '../layout/Header';
import LoadingSkeleton from '../layout/LoadingSkeleton';

export default function OptionScannerPage() {
  const scanner = useOptionScanner();
  const { result, loading, error } = scanner;
  const schwab = useSchwabStatus();

  return (
    <div className="h-screen flex flex-col bg-slate-100 dark:bg-slate-900">
      <Header sessions={[]} onLoadSession={() => {}} />

      <div className="flex-1 flex overflow-hidden">
        <ChainFilters
          ticker={scanner.ticker} setTicker={scanner.setTicker}
          strategy={scanner.strategy} setStrategy={scanner.setStrategy}
          costBasis={scanner.costBasis} setCostBasis={scanner.setCostBasis}
          sharesHeld={scanner.sharesHeld} setSharesHeld={scanner.setSharesHeld}
          capitalAvailable={scanner.capitalAvailable} setCapitalAvailable={scanner.setCapitalAvailable}
          minDte={scanner.minDte} setMinDte={scanner.setMinDte}
          maxDte={scanner.maxDte} setMaxDte={scanner.setMaxDte}
          returnTarget={scanner.returnTarget} setReturnTarget={scanner.setReturnTarget}
          callDistance={scanner.callDistance} setCallDistance={scanner.setCallDistance}
          minDelta={scanner.minDelta} setMinDelta={scanner.setMinDelta}
          maxDelta={scanner.maxDelta} setMaxDelta={scanner.setMaxDelta}
          earningsBuffer={scanner.earningsBuffer} setEarningsBuffer={scanner.setEarningsBuffer}
          onScan={scanner.runScan}
          loading={loading}
          onReset={scanner.reset}
          schwabAvailable={schwab.isAvailable}
          schwabLoading={schwab.loading}
        />

        <main className="flex-1 overflow-y-auto p-6 space-y-4">
          {/* Schwab API Status Banner */}
          {!schwab.loading && !schwab.isAvailable && (
            <div
              data-testid="schwab-status-banner"
              className="flex items-center gap-3 px-4 py-3 rounded-lg border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/30 text-amber-800 dark:text-amber-200"
              role="alert"
            >
              <span className="inline-block w-2.5 h-2.5 rounded-full bg-red-500 shrink-0" data-testid="schwab-status-dot" />
              <span className="text-sm font-medium">
                Schwab API: Not Connected
              </span>
              <span className="text-sm text-amber-600 dark:text-amber-400">
                &mdash; Options scanning requires a configured Schwab API connection. Visit Settings to set up your credentials.
              </span>
            </div>
          )}
          {!schwab.loading && schwab.isAvailable && (
            <div
              data-testid="schwab-status-banner"
              className="flex items-center gap-3 px-4 py-3 rounded-lg border border-green-300 dark:border-green-700 bg-green-50 dark:bg-green-900/30 text-green-800 dark:text-green-200"
              role="status"
            >
              <span className="inline-block w-2.5 h-2.5 rounded-full bg-green-500 shrink-0" data-testid="schwab-status-dot" />
              <span className="text-sm font-medium">
                Schwab API: Connected
              </span>
            </div>
          )}
          {loading ? (
            <LoadingSkeleton />
          ) : error && !result ? (
            <div className="h-full flex items-center justify-center">
              <div className="max-w-md text-center">
                <svg className="w-16 h-16 mx-auto mb-4 text-red-300 dark:text-red-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v3.75m9-.75a9 9 0 11-18 0 9 9 0 0118 0zm-9 3.75h.008v.008H12v-.008z" />
                </svg>
                <h2 className="text-lg font-medium text-slate-700 dark:text-slate-200 mb-2">Scan failed</h2>
                <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
              </div>
            </div>
          ) : !result ? (
            <div className="h-full flex items-center justify-center">
              <div className="text-center max-w-md">
                <svg className="w-20 h-20 mx-auto mb-4 text-slate-200 dark:text-slate-700" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M3 4a1 1 0 011-1h16a1 1 0 011 1v2.586a1 1 0 01-.293.707l-6.414 6.414a1 1 0 00-.293.707V17l-4 4v-6.586a1 1 0 00-.293-.707L3.293 7.293A1 1 0 013 6.586V4z" />
                </svg>
                <h2 className="text-lg font-medium text-slate-600 dark:text-slate-300 mb-2">
                  Scan the option chain
                </h2>
                <p className="text-sm text-slate-400 dark:text-slate-500">
                  Enter a ticker, select your strategy, and click &quot;Scan Options&quot; to find wheel strategy opportunities.
                </p>
              </div>
            </div>
          ) : (
            <>
              {/* Market Context Header */}
              <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl p-4">
                <div className="flex items-start justify-between flex-wrap gap-3">
                  <div>
                    <h2 className="text-xl font-bold text-slate-900 dark:text-white">
                      {result.ticker} &mdash; {result.strategy === 'covered_call' ? 'Covered Call' : 'Cash-Secured Put'} Scan
                    </h2>
                    <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-sm text-slate-600 dark:text-slate-400">
                      <span>Price: <strong>${result.current_price.toFixed(2)}</strong></span>
                      {result.earnings_date && (
                        <span>Earnings: <strong>{result.earnings_date}</strong></span>
                      )}
                      {result.market_context?.beta != null && (
                        <span>Beta: <strong>{result.market_context.beta.toFixed(2)}</strong></span>
                      )}
                      {result.market_context?.vix != null && (
                        <span>VIX: <strong>{result.market_context.vix.toFixed(1)}</strong></span>
                      )}
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-2xl font-bold text-blue-600 dark:text-blue-400">
                      {result.recommendations.length}
                    </div>
                    <div className="text-xs text-slate-500 dark:text-slate-400">opportunities</div>
                  </div>
                </div>
              </div>

              {/* Strike Table */}
              <StrikeTable
                recommendations={result.recommendations}
                selectedStrikes={scanner.selectedStrikes}
                onToggleSelection={scanner.toggleStrikeSelection}
              />

              {/* Risk/Reward Comparison */}
              <RiskRewardPanel
                selectedStrikes={scanner.selectedStrikes}
                strategy={result.strategy}
              />

              {/* Rejected Strikes */}
              {result.rejected.length > 0 && (
                <details className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl">
                  <summary className="px-4 py-3 cursor-pointer text-sm font-medium text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-700/50 rounded-xl">
                    Rejected Strikes ({result.rejected.length})
                  </summary>
                  <div className="px-4 pb-4 space-y-1.5">
                    {result.rejected.slice(0, 20).map((r, i) => (
                      <div key={i} className="flex justify-between text-xs text-slate-600 dark:text-slate-400 py-1 border-b border-slate-100 dark:border-slate-700 last:border-0">
                        <span className="font-medium">${r.strike.toFixed(2)} {r.expiration}</span>
                        <span className="text-red-500 dark:text-red-400 text-right ml-4">{r.rejection_reasons.join('; ')}</span>
                      </div>
                    ))}
                    {result.rejected.length > 20 && (
                      <p className="text-xs text-slate-400">...and {result.rejected.length - 20} more</p>
                    )}
                  </div>
                </details>
              )}
            </>
          )}
        </main>
      </div>
    </div>
  );
}
