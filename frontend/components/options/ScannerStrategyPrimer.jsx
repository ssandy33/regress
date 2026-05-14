// Top-of-page educational card explaining the current strategy (Covered Call
// or Cash-Secured Put) in plain English.
//
// Collapsed by default on first visit. Per-strategy collapse state is
// persisted to localStorage so the primer stays out of the way once the user
// has read it. Reacts to the active `strategy` prop so the copy and the
// localStorage key swap together.
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

const STORAGE_KEY_PREFIX = 'scanner-primer-collapsed-';

// Map the strategy prop (which may be 'covered_call' / 'cash_secured_put' from
// the API, or the short 'cc' / 'csp' used internally) into a stable copy/storage key.
function normalizeStrategy(strategy) {
  if (strategy === 'covered_call' || strategy === 'cc') return 'cc';
  if (strategy === 'cash_secured_put' || strategy === 'csp') return 'csp';
  return 'cc';
}

function readPersistedCollapsed(key) {
  if (typeof window === 'undefined') return true;
  try {
    const raw = window.localStorage.getItem(key);
    if (raw === null) return true; // default = collapsed on first visit
    return raw === '1';
  } catch {
    return true;
  }
}

function writePersistedCollapsed(key, collapsed) {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(key, collapsed ? '1' : '0');
  } catch {
    // localStorage may be disabled (Safari private mode, etc.) — silently
    // ignore. The primer will still toggle visually within the session.
  }
}

export default function ScannerStrategyPrimer({ strategy = 'cc' }) {
  const normalized = normalizeStrategy(strategy);
  const storageKey = `${STORAGE_KEY_PREFIX}${normalized}`;

  // Derived-state-from-props pattern. Keep the last seen storageKey alongside
  // the collapsed flag; when the key changes (strategy toggled), refresh both
  // during render. Avoids the react-hooks/set-state-in-effect rule (#198) — no
  // useEffect needed for this kind of prop-driven re-derivation.
  const [persisted, setPersisted] = useState(() => ({
    key: storageKey,
    collapsed: readPersistedCollapsed(storageKey),
  }));
  if (persisted.key !== storageKey) {
    setPersisted({ key: storageKey, collapsed: readPersistedCollapsed(storageKey) });
  }
  const collapsed = persisted.collapsed;

  const copy = COPY[normalized];
  const expanded = !collapsed;

  const handleToggle = () => {
    const nextCollapsed = !collapsed;
    setPersisted({ key: storageKey, collapsed: nextCollapsed });
    writePersistedCollapsed(storageKey, nextCollapsed);
  };

  return (
    <section
      data-testid="scanner-strategy-primer"
      data-strategy={normalized}
      className="bg-blue-50 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-900 rounded-xl"
    >
      <button
        type="button"
        onClick={handleToggle}
        data-testid="scanner-strategy-primer-toggle"
        className="w-full px-4 py-3 flex items-center justify-between gap-3 text-left focus:outline-none focus:ring-2 focus:ring-blue-500 rounded-xl"
        aria-expanded={expanded}
        aria-controls="scanner-strategy-primer-body"
        aria-label={`${expanded ? 'Hide' : 'Show'} strategy primer`}
      >
        <span className="flex items-center gap-2 min-w-0">
          <span
            className="text-blue-600 dark:text-blue-300 text-xs font-semibold uppercase tracking-wide"
            aria-hidden="true"
          >
            Primer
          </span>
          <span className="text-sm font-semibold text-slate-900 dark:text-white truncate">
            {copy.title}
          </span>
        </span>
        <span
          className="text-slate-500 dark:text-slate-400 text-xs shrink-0"
          aria-hidden="true"
        >
          {expanded ? 'Hide' : 'Show'}
        </span>
      </button>
      {expanded && (
        <div
          id="scanner-strategy-primer-body"
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
