import { useState } from 'react';

export default function StrikeTable({ recommendations, selectedStrikes, onToggleSelection }) {
  const [sortField, setSortField] = useState('rank');
  const [sortDir, setSortDir] = useState('asc');
  const [expandedRow, setExpandedRow] = useState(null);

  const handleSort = (field) => {
    if (sortField === field) {
      setSortDir(sortDir === 'asc' ? 'desc' : 'asc');
    } else {
      setSortField(field);
      setSortDir('asc');
    }
  };

  const sorted = [...recommendations].sort((a, b) => {
    const av = a[sortField] ?? 0;
    const bv = b[sortField] ?? 0;
    return sortDir === 'asc' ? (av > bv ? 1 : -1) : (av < bv ? 1 : -1);
  });

  if (recommendations.length === 0) {
    return (
      <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl p-8 text-center">
        <p className="text-slate-500 dark:text-slate-400">No strikes passed all filters. Try widening your parameters.</p>
      </div>
    );
  }

  return (
    <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 dark:bg-slate-900 border-b border-slate-200 dark:border-slate-700">
            <tr>
              <th className="px-3 py-2 text-left w-8" />
              <SortHeader field="rank" label="#" sortField={sortField} sortDir={sortDir} onSort={handleSort} align="left" />
              <SortHeader field="strike" label="Strike" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
              <SortHeader field="expiration" label="Exp" sortField={sortField} sortDir={sortDir} onSort={handleSort} align="left" />
              <SortHeader field="dte" label="DTE" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
              <th className="px-3 py-2 text-right text-xs font-medium text-slate-500 dark:text-slate-400">Bid/Ask</th>
              <SortHeader field="delta" label="Delta" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
              <SortHeader field="open_interest" label="OI" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
              <SortHeader field="total_premium" label="Premium" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
              <SortHeader field="return_on_capital_pct" label="Return%" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
              <SortHeader field="annualized_return_pct" label="Ann.%" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
              <SortHeader field="distance_from_price_pct" label="Dist.%" sortField={sortField} sortDir={sortDir} onSort={handleSort} />
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-700">
            {sorted.map((s) => {
              const key = `${s.strike}-${s.expiration}`;
              const isSelected = selectedStrikes.some((sel) => `${sel.strike}-${sel.expiration}` === key);
              const isExpanded = expandedRow === key;
              const allPass = s.rule_compliance && Object.values(s.rule_compliance).every(Boolean);

              return (
                <RowGroup key={key}>
                  <tr
                    className={`hover:bg-slate-50 dark:hover:bg-slate-700/50 cursor-pointer transition-colors ${isSelected ? 'bg-blue-50 dark:bg-blue-900/20' : ''}`}
                    onClick={() => setExpandedRow(isExpanded ? null : key)}
                  >
                    <td className="px-3 py-2" onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => onToggleSelection(s)}
                        className="rounded border-slate-300 dark:border-slate-600 text-blue-600 focus:ring-blue-500"
                      />
                    </td>
                    <td className="px-3 py-2 text-slate-500 dark:text-slate-400">{s.rank}</td>
                    <td className={`px-3 py-2 text-right font-medium ${allPass ? 'text-green-700 dark:text-green-400' : 'text-yellow-700 dark:text-yellow-400'}`}>
                      ${s.strike.toFixed(2)}
                    </td>
                    <td className="px-3 py-2 text-slate-700 dark:text-slate-300">{s.expiration}</td>
                    <td className="px-3 py-2 text-right text-slate-700 dark:text-slate-300">{s.dte}</td>
                    <td className="px-3 py-2 text-right text-xs text-slate-500 dark:text-slate-400">
                      {s.bid.toFixed(2)}/{s.ask.toFixed(2)}
                    </td>
                    <td className="px-3 py-2 text-right text-slate-700 dark:text-slate-300">{s.delta.toFixed(2)}</td>
                    <td className="px-3 py-2 text-right text-slate-700 dark:text-slate-300">{s.open_interest.toLocaleString()}</td>
                    <td className="px-3 py-2 text-right font-medium text-slate-900 dark:text-white">${s.total_premium.toFixed(2)}</td>
                    <td className="px-3 py-2 text-right font-medium text-blue-600 dark:text-blue-400">{s.return_on_capital_pct.toFixed(2)}%</td>
                    <td className="px-3 py-2 text-right text-slate-700 dark:text-slate-300">{s.annualized_return_pct.toFixed(1)}%</td>
                    <td className="px-3 py-2 text-right text-slate-700 dark:text-slate-300">{s.distance_from_price_pct.toFixed(1)}%</td>
                  </tr>
                  {isExpanded && (
                    <tr>
                      <td colSpan={12} className="px-6 py-4 bg-slate-50 dark:bg-slate-900/50">
                        <ExpandedDetails strike={s} />
                      </td>
                    </tr>
                  )}
                </RowGroup>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RowGroup({ children }) {
  return <>{children}</>;
}

function SortHeader({ field, label, sortField, sortDir, onSort, align = 'right' }) {
  const active = sortField === field;
  return (
    <th
      className={`px-3 py-2 text-${align} text-xs font-medium text-slate-500 dark:text-slate-400 cursor-pointer hover:text-slate-700 dark:hover:text-slate-200 select-none`}
      onClick={() => onSort(field)}
    >
      {label}
      {active && <span className="ml-0.5">{sortDir === 'asc' ? '\u2191' : '\u2193'}</span>}
    </th>
  );
}

function ExpandedDetails({ strike }) {
  return (
    <div className="grid grid-cols-3 gap-6 text-sm">
      <div>
        <h4 className="font-medium text-slate-900 dark:text-white mb-2">
          Greeks
          {strike.greeks_source && strike.greeks_source !== 'market' && (
            <span className="ml-1.5 text-[10px] font-normal px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-900/40 text-blue-600 dark:text-blue-400">
              {strike.greeks_source === 'calculated' ? 'BS calc' : strike.greeks_source}
            </span>
          )}
        </h4>
        <div className="space-y-1 text-xs text-slate-600 dark:text-slate-400">
          <div>Delta: {strike.delta.toFixed(3)}</div>
          <div>Gamma: {strike.gamma?.toFixed(4) ?? 'N/A'}</div>
          <div>Theta: {strike.theta?.toFixed(4) ?? 'N/A'}</div>
          <div>Vega: {strike.vega?.toFixed(4) ?? 'N/A'}</div>
          <div>IV: {strike.iv ? (strike.iv * 100).toFixed(1) + '%' : 'N/A'}</div>
        </div>
      </div>
      <div>
        <h4 className="font-medium text-slate-900 dark:text-white mb-2">Metrics</h4>
        <div className="space-y-1 text-xs text-slate-600 dark:text-slate-400">
          <div>Premium/Contract: ${strike.premium_per_contract.toFixed(2)}</div>
          <div>Max Profit: ${strike.max_profit.toFixed(2)}</div>
          {strike.breakeven != null && <div>Breakeven: ${strike.breakeven.toFixed(2)}</div>}
          {strike.distance_from_basis_pct != null && <div>Dist. from Basis: {strike.distance_from_basis_pct.toFixed(1)}%</div>}
          <div>50% Target: ${strike.fifty_pct_profit_target.toFixed(2)}</div>
        </div>
      </div>
      <div>
        <h4 className="font-medium text-slate-900 dark:text-white mb-2">Rule Compliance</h4>
        <div className="space-y-1 text-xs">
          <RuleCheck label="10% Rule" passed={strike.rule_compliance.passes_10pct_rule} />
          <RuleCheck label="DTE Range" passed={strike.rule_compliance.passes_dte_range} />
          <RuleCheck label="Delta Range" passed={strike.rule_compliance.passes_delta_range} />
          <RuleCheck label="Earnings Check" passed={strike.rule_compliance.passes_earnings_check} />
          <RuleCheck label="Return Target" passed={strike.rule_compliance.passes_return_target} />
        </div>
        {strike.flags.length > 0 && (
          <div className="mt-2 text-xs text-yellow-600 dark:text-yellow-400">
            Flags: {strike.flags.join(', ')}
          </div>
        )}
      </div>
    </div>
  );
}

function RuleCheck({ label, passed }) {
  return (
    <div className={passed ? 'text-green-600 dark:text-green-400' : 'text-red-600 dark:text-red-400'}>
      {passed ? '\u2713' : '\u2717'} {label}
    </div>
  );
}
