// Phase 1.5 mock — placeholder for spec implementation. Replace during Phase 3.
//
// Top-of-page educational card that explains the current strategy (Covered Call
// or Cash-Secured Put) in plain English. Collapsed by default; dismissal is
// persisted per-strategy in localStorage. Re-shown via a "Show primers" link
// rendered by ChainFilters footer.
//
// Spec: frontend/design-specs/scanner-education-v0.5.7.md (Affordance 1)

import { useState } from 'react';

const COPY = {
  cc: {
    title: 'Covered Call — what you are about to do',
    oneLiner:
      'You own 100+ shares. You are renting them out to someone who has the right to buy them from you at the strike price.',
    bullets: [
      'You collect the premium up front. It is yours to keep no matter what.',
      'If the stock closes below the strike at expiration, the contract expires and you keep your shares.',
      'If the stock closes above the strike, your shares get called away at that strike — capping your upside.',
      'Best when you are neutral-to-mildly-bullish and would be happy to sell at the strike.',
    ],
    whenToUse:
      'Use this on shares you already own and would not mind parting with at the strike price. The 10% rule limits the strike to no less than ~90% of cost basis so you cannot be forced to sell at a loss.',
  },
  csp: {
    title: 'Cash-Secured Put — what you are about to do',
    oneLiner:
      'You set aside cash to buy 100 shares at the strike price. Someone pays you for the obligation to do so.',
    bullets: [
      'You collect the premium up front. It is yours to keep no matter what.',
      'If the stock closes above the strike at expiration, the contract expires worthless and you keep your premium and your cash.',
      'If the stock closes below the strike, you are assigned the shares at the strike price.',
      'Best when you would be happy to own the shares at the strike — treat the strike as your "buy" price.',
    ],
    whenToUse:
      'Use this when you want to acquire shares at a discount or simply collect income on cash you would otherwise hold. Make sure you have the full strike × 100 in cash before opening the position.',
  },
};

export default function ScannerStrategyPrimer({
  strategy = 'cc',
  defaultExpanded = false,
  onDismiss,
}) {
  const [expanded, setExpanded] = useState(defaultExpanded);
  const copy = COPY[strategy] || COPY.cc;

  return (
    <section
      data-testid="scanner-strategy-primer"
      className="bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-900 rounded-xl"
    >
      <header className="px-4 py-3 flex items-center justify-between gap-3">
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          data-testid="scanner-strategy-primer-toggle"
          className="flex items-center gap-2 text-left flex-1 min-w-0"
          aria-expanded={expanded}
        >
          <span
            className="text-blue-600 dark:text-blue-300 text-xs font-semibold uppercase tracking-wide"
            aria-hidden="true"
          >
            Primer
          </span>
          <span className="text-sm font-semibold text-slate-900 dark:text-white truncate">
            {copy.title}
          </span>
          <span
            className="ml-auto text-slate-500 dark:text-slate-400 text-xs"
            aria-hidden="true"
          >
            {expanded ? 'Hide' : 'Show'}
          </span>
        </button>
        <button
          type="button"
          onClick={onDismiss}
          data-testid="scanner-strategy-primer-dismiss"
          className="text-xs text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
          aria-label="Dismiss primer"
        >
          Dismiss
        </button>
      </header>
      {expanded && (
        <div
          data-testid="scanner-strategy-primer-body"
          className="px-4 pb-4 pt-1 space-y-3 text-sm text-slate-700 dark:text-slate-200"
        >
          <p className="font-medium">{copy.oneLiner}</p>
          <ul className="list-disc list-outside ml-5 space-y-1.5 text-sm">
            {copy.bullets.map((b, i) => (
              <li key={i}>{b}</li>
            ))}
          </ul>
          <p className="text-xs text-slate-600 dark:text-slate-300">
            <span className="font-semibold">When to use it: </span>
            {copy.whenToUse}
          </p>
        </div>
      )}
    </section>
  );
}
