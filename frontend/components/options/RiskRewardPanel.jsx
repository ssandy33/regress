export default function RiskRewardPanel({ selectedStrikes, strategy }) {
  if (selectedStrikes.length === 0) {
    return (
      <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl p-6 text-center text-sm text-slate-500 dark:text-slate-400">
        Select 2-3 strikes from the table above to compare risk/reward profiles
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl p-6">
      <h3 className="text-base font-semibold text-slate-900 dark:text-white mb-4">
        Risk/Reward Comparison
      </h3>
      <div className={`grid gap-4 ${selectedStrikes.length === 1 ? 'grid-cols-1 max-w-sm' : selectedStrikes.length === 2 ? 'grid-cols-2' : 'grid-cols-3'}`}>
        {selectedStrikes.map((s) => (
          <ComparisonCard
            key={`${s.strike}-${s.expiration}`}
            strike={s}
            strategy={strategy}
            allStrikes={selectedStrikes}
          />
        ))}
      </div>
    </div>
  );
}

function ComparisonCard({ strike, strategy, allStrikes }) {
  const highlights = getHighlights(strike, allStrikes);
  const typeLabel = strategy === 'covered_call' ? 'Call' : 'Put';

  return (
    <div className="border border-slate-200 dark:border-slate-700 rounded-lg overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 bg-slate-50 dark:bg-slate-900 border-b border-slate-200 dark:border-slate-700">
        <div className="text-lg font-bold text-slate-900 dark:text-white">
          ${strike.strike.toFixed(2)} {typeLabel}
        </div>
        <div className="text-xs text-slate-500 dark:text-slate-400">
          {strike.expiration} ({strike.dte}d)
        </div>
      </div>

      {/* Metrics */}
      <div className="px-4 py-3 space-y-1.5">
        <MetricRow label="Premium" value={`$${strike.total_premium.toFixed(2)}`} />
        <MetricRow label="Return" value={`${strike.return_on_capital_pct.toFixed(2)}%`} highlight />
        <MetricRow label="Annualized" value={`${strike.annualized_return_pct.toFixed(1)}%`} />
        <MetricRow label="Distance" value={`${strike.distance_from_price_pct.toFixed(1)}%`} />
        <MetricRow label="Delta" value={strike.delta.toFixed(2)} />
        <MetricRow label="50% Target" value={`$${strike.fifty_pct_profit_target.toFixed(2)}`} />
        {strike.breakeven != null && (
          <MetricRow label="Breakeven" value={`$${strike.breakeven.toFixed(2)}`} />
        )}
      </div>

      {/* Highlights */}
      {highlights.length > 0 && (
        <div className="px-4 py-3 border-t border-slate-200 dark:border-slate-700 space-y-1">
          {highlights.map((h, i) => (
            <div
              key={i}
              className={`text-xs ${h.type === 'pro' ? 'text-green-600 dark:text-green-400' : 'text-yellow-600 dark:text-yellow-400'}`}
            >
              {h.type === 'pro' ? '\u2713' : '\u26A0'} {h.text}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function MetricRow({ label, value, highlight }) {
  return (
    <div className="flex justify-between text-sm">
      <span className="text-slate-500 dark:text-slate-400">{label}</span>
      <span className={`font-medium ${highlight ? 'text-blue-600 dark:text-blue-400' : 'text-slate-900 dark:text-white'}`}>
        {value}
      </span>
    </div>
  );
}

function getHighlights(strike, allStrikes) {
  const highlights = [];

  // Find best values for comparison
  const maxReturn = Math.max(...allStrikes.map((s) => s.return_on_capital_pct));
  const maxDistance = Math.max(...allStrikes.map((s) => s.distance_from_price_pct));
  const maxPremium = Math.max(...allStrikes.map((s) => s.total_premium));
  const maxOI = Math.max(...allStrikes.map((s) => s.open_interest));

  if (allStrikes.length > 1) {
    if (strike.return_on_capital_pct === maxReturn) {
      highlights.push({ type: 'pro', text: 'Highest return' });
    }
    if (strike.distance_from_price_pct === maxDistance) {
      highlights.push({ type: 'pro', text: 'Safest strike' });
    }
    if (strike.total_premium === maxPremium) {
      highlights.push({ type: 'pro', text: 'Best total premium' });
    }
    if (strike.open_interest === maxOI) {
      highlights.push({ type: 'pro', text: 'Best liquidity' });
    }
  }

  if (strike.dte > 45) {
    highlights.push({ type: 'warn', text: 'Longer DTE' });
  }
  if (Math.abs(strike.delta) > 0.30) {
    highlights.push({ type: 'warn', text: 'Higher delta risk' });
  }
  if (strike.return_on_capital_pct < 1.0) {
    highlights.push({ type: 'warn', text: 'Below 1% target' });
  }

  return highlights;
}
