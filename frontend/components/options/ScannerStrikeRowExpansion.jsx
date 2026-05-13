// Phase 1.5 mock — placeholder for spec implementation. Replace during Phase 3.
//
// Single-row accordion content for a strike. Appends a "What this trade
// commits you to" sub-section to the existing Greeks / Metrics / Rule
// Compliance panel — it does NOT replace the panel.
//
// All math derives from fields the scanner already returns:
//   premium_per_contract, breakeven, fifty_pct_profit_target
// plus user-input context (cost basis, shares held, capital available).
//
// Spec: frontend/design-specs/scanner-education-v0.5.7.md (Affordance 3)

function formatUsd(n, digits = 2) {
  if (n == null) return '—';
  const sign = n < 0 ? '-' : '';
  return `${sign}$${Math.abs(n).toFixed(digits)}`;
}

// Build the plain-English outcome scenarios for a Covered Call.
function ccScenarios({ strike, premium_per_contract, breakeven, cost_basis_per_share, contracts = 1, earnings_in_window }) {
  const premiumTotal = premium_per_contract * contracts;
  const sharesAtRisk = 100 * contracts;
  const calledAwayProceeds = strike * sharesAtRisk;
  const calledAwayPL = calledAwayProceeds - cost_basis_per_share * sharesAtRisk + premiumTotal;
  return {
    obligation: `If assigned, you sell ${sharesAtRisk} share${sharesAtRisk === 100 ? '' : 's'} at $${strike.toFixed(2)}. Total proceeds: ${formatUsd(calledAwayProceeds)}.`,
    premium: `You collect ${formatUsd(premiumTotal)} in premium right now — yours to keep regardless of outcome.`,
    breakeven: breakeven != null
      ? `Your effective break-even if called away: ${formatUsd(breakeven)} per share (cost basis minus premium received).`
      : null,
    outcomes: [
      {
        label: 'Stock stays below the strike',
        text: `Contract expires worthless. You keep all ${sharesAtRisk} shares and the ${formatUsd(premiumTotal)} premium. Ready to write another call.`,
      },
      {
        label: 'Stock closes above the strike',
        text: `Shares are called away at $${strike.toFixed(2)}. Total P/L on this position: ${formatUsd(calledAwayPL)} (proceeds + premium − cost basis). Upside above the strike is forfeit.`,
      },
      {
        label: 'Stock spikes far above the strike',
        text: 'Same outcome as above — your shares are called at the strike, so the upside is capped. The premium you collected is your max gain beyond the strike.',
      },
    ],
    earnings_in_window: earnings_in_window === true,
  };
}

// Build the plain-English outcome scenarios for a Cash-Secured Put.
function cspScenarios({ strike, premium_per_contract, breakeven, contracts = 1, earnings_in_window }) {
  const premiumTotal = premium_per_contract * contracts;
  const sharesAtRisk = 100 * contracts;
  const cashAtRisk = strike * sharesAtRisk;
  return {
    obligation: `You set aside ${formatUsd(cashAtRisk)} as collateral. If assigned, you buy ${sharesAtRisk} share${sharesAtRisk === 100 ? '' : 's'} at $${strike.toFixed(2)}.`,
    premium: `You collect ${formatUsd(premiumTotal)} in premium right now — yours to keep regardless of outcome.`,
    breakeven: breakeven != null
      ? `Your effective entry if assigned: ${formatUsd(breakeven)} per share (strike minus premium received).`
      : null,
    outcomes: [
      {
        label: 'Stock stays above the strike',
        text: `Contract expires worthless. You keep your ${formatUsd(cashAtRisk)} and the ${formatUsd(premiumTotal)} premium. Free to sell another put.`,
      },
      {
        label: 'Stock closes below the strike',
        text: `You are assigned. ${formatUsd(cashAtRisk)} is converted into ${sharesAtRisk} shares at $${strike.toFixed(2)}. Your effective entry is ${formatUsd(breakeven ?? strike - premium_per_contract)} per share.`,
      },
      {
        label: 'Stock drops far below the strike',
        text: 'Same assignment, but the shares are now worth less than your entry. You are still long the shares; you can write covered calls on them once you own them ("the wheel").',
      },
    ],
    earnings_in_window: earnings_in_window === true,
  };
}

export default function ScannerStrikeRowExpansion({
  strategy = 'cc',
  strike, // numeric strike $
  expiration, // 'YYYY-MM-DD'
  dte,
  premium_per_contract,
  breakeven,
  fifty_pct_profit_target,
  cost_basis_per_share,
  contracts = 1,
  shares_held,
  earnings_in_window = false,
  // Mocked Greeks for the existing panel context
  greeks = { delta: 0.28, gamma: 0.05, theta: -0.012, vega: 0.08, iv: 0.34 },
}) {
  const built =
    strategy === 'csp'
      ? cspScenarios({ strike, premium_per_contract, breakeven, contracts, earnings_in_window })
      : ccScenarios({ strike, premium_per_contract, breakeven, cost_basis_per_share, contracts, earnings_in_window });

  return (
    <div
      data-testid="scanner-strike-row-expansion"
      className="space-y-4"
    >
      {/* Existing panel — Greeks / Metrics / Rule Compliance (preserved) */}
      <div className="grid grid-cols-3 gap-6 text-sm">
        <div>
          <h4 className="font-medium text-slate-900 dark:text-white mb-2">Greeks</h4>
          <div className="space-y-1 text-xs text-slate-600 dark:text-slate-400">
            <div>Delta: {greeks.delta.toFixed(3)}</div>
            <div>Gamma: {greeks.gamma.toFixed(4)}</div>
            <div>Theta: {greeks.theta.toFixed(4)}</div>
            <div>Vega: {greeks.vega.toFixed(4)}</div>
            <div>IV: {(greeks.iv * 100).toFixed(1)}%</div>
          </div>
        </div>
        <div>
          <h4 className="font-medium text-slate-900 dark:text-white mb-2">Metrics</h4>
          <div className="space-y-1 text-xs text-slate-600 dark:text-slate-400">
            <div>Premium/Contract: {formatUsd(premium_per_contract)}</div>
            <div>Breakeven: {formatUsd(breakeven)}</div>
            <div>50% Target: {formatUsd(fifty_pct_profit_target)}</div>
            <div>DTE: {dte}</div>
            <div>Exp: {expiration}</div>
          </div>
        </div>
        <div>
          <h4 className="font-medium text-slate-900 dark:text-white mb-2">Rule Compliance</h4>
          <div className="space-y-1 text-xs">
            <div className="text-green-600 dark:text-green-400">✓ 10% Rule</div>
            <div className="text-green-600 dark:text-green-400">✓ DTE Range</div>
            <div className="text-green-600 dark:text-green-400">✓ Delta Range</div>
            <div className="text-green-600 dark:text-green-400">✓ Return Target</div>
            <div
              className={
                earnings_in_window
                  ? 'text-yellow-600 dark:text-yellow-400'
                  : 'text-green-600 dark:text-green-400'
              }
            >
              {earnings_in_window ? '! ' : '✓ '}Earnings Check
            </div>
          </div>
        </div>
      </div>

      {/* NEW: "What this trade commits you to" sub-section — appended */}
      <div
        data-testid="scanner-strike-row-commitment"
        className="border-t border-slate-200 dark:border-slate-700 pt-4"
      >
        <h4 className="font-medium text-slate-900 dark:text-white mb-2 flex items-center gap-2">
          What this trade commits you to
          <span className="text-[10px] font-medium uppercase tracking-wide px-1.5 py-0.5 rounded bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300">
            Plain English
          </span>
        </h4>
        <div className="space-y-3 text-sm text-slate-700 dark:text-slate-200">
          <div className="grid sm:grid-cols-2 gap-3">
            <div className="bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-700 rounded-lg p-3">
              <p className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                Your obligation
              </p>
              <p>{built.obligation}</p>
            </div>
            <div className="bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-700 rounded-lg p-3">
              <p className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1">
                Premium collected
              </p>
              <p>{built.premium}</p>
              {built.breakeven && (
                <p className="text-xs text-slate-600 dark:text-slate-400 mt-1">{built.breakeven}</p>
              )}
            </div>
          </div>

          <div>
            <p className="text-xs font-semibold text-slate-500 dark:text-slate-400 uppercase tracking-wide mb-1.5">
              Outcome scenarios at expiration
            </p>
            <ol className="list-decimal list-outside ml-5 space-y-1.5 text-sm">
              {built.outcomes.map((o, i) => (
                <li key={i}>
                  <span className="font-semibold">{o.label}: </span>
                  <span>{o.text}</span>
                </li>
              ))}
            </ol>
          </div>

          {built.earnings_in_window && (
            <div
              data-testid="scanner-strike-row-earnings-flag"
              className="text-xs bg-yellow-50 dark:bg-yellow-900/30 border border-yellow-200 dark:border-yellow-800 rounded-md px-3 py-2 text-yellow-800 dark:text-yellow-200"
            >
              <span className="font-semibold">Earnings within the contract window. </span>
              Expect larger price swings between now and expiration — the outcome scenarios above
              can shift quickly. Consider sizing down or skipping this expiration.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
