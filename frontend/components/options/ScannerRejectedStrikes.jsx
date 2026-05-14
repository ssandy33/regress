// Humanized rejected-strikes disclosure. Replaces the inline red
// `rejection_reasons` join with a bulleted list of plain-English sentences
// in neutral slate color.
//
// Source of truth for the human sentences is the backend's `human_reasons`
// field on each `RejectedStrike` (populated by
// `backend/app/services/rejection_messages.py`). The fallback CLIENT_COPY
// map below is purely defensive — if the backend ever returns an empty
// `human_reasons` (legacy payload, mis-deploy), the client maps raw codes
// to short sentences so the user is not staring at machine codes. Unknown
// raw codes degrade to the raw string unchanged.
//
// Spec: frontend/design-specs/scanner-education-v0.5.7.md (Affordance 4)

import { useState } from 'react';

// Defensive fallback only — the backend is the canonical source.
// Keys are the code prefix (everything before the colon in a raw rejection).
const CLIENT_COPY_FALLBACK = {
  fails_10pct_rule:
    'Strike is below 90% of your cost basis — selling here could force you to part with shares at a loss.',
  itm_put:
    'Put is already in the money. CSPs work best below current price; this would be immediate intrinsic loss.',
  delta_out_of_range:
    'Delta is outside your target band — too aggressive or too conservative for this scan.',
  low_open_interest:
    'Open interest is low. Liquidity may be thin, making it hard to exit at a fair price.',
  zero_bid:
    'No buyers are quoting this contract right now. You cannot reliably sell here.',
  return_below_target:
    'Premium is below your minimum return-on-capital target.',
  return_above_cap:
    'Return is above your sanity-check cap — likely a stale quote or an unusual contract.',
};

function humanizeFallback(raw) {
  // Extract the code prefix (before the first colon) and look it up. If the
  // raw string has no colon, treat the whole string as the code.
  const codeMatch = /^([a-z_]+)/i.exec(raw);
  const code = codeMatch ? codeMatch[1] : raw;
  return CLIENT_COPY_FALLBACK[code] || raw;
}

function RejectedRow({ rejection }) {
  const reasons =
    rejection.human_reasons && rejection.human_reasons.length > 0
      ? rejection.human_reasons
      : (rejection.rejection_reasons || []).map(humanizeFallback);

  return (
    <li
      data-testid="scanner-rejected-strike-row"
      className="py-2 border-b border-slate-100 dark:border-slate-700 last:border-0"
    >
      <div className="flex items-baseline justify-between gap-3 mb-1">
        <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
          ${rejection.strike.toFixed(2)} {rejection.expiration}
        </span>
        <span className="text-xs text-slate-500 dark:text-slate-400">
          {reasons.length === 1 ? '1 reason' : `${reasons.length} reasons`}
        </span>
      </div>
      {reasons.length === 1 ? (
        <p className="text-xs text-slate-600 dark:text-slate-300">{reasons[0]}</p>
      ) : (
        <ul className="list-disc list-outside ml-5 space-y-0.5 text-xs text-slate-600 dark:text-slate-300">
          {reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}
    </li>
  );
}

export default function ScannerRejectedStrikes({
  rejected = [],
  defaultOpen = false,
  visibleCount = 20,
}) {
  const [open, setOpen] = useState(defaultOpen);
  if (rejected.length === 0) return null;

  const shown = rejected.slice(0, visibleCount);
  const hiddenCount = rejected.length - shown.length;

  return (
    <section
      data-testid="scanner-rejected-strikes"
      className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl"
    >
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        data-testid="scanner-rejected-strikes-toggle"
        className="w-full px-4 py-3 flex items-center justify-between text-sm font-medium text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-700/50 rounded-xl focus:outline-none focus:ring-2 focus:ring-blue-500"
        aria-expanded={open}
      >
        <span>Rejected Strikes ({rejected.length})</span>
        <span className="text-xs text-slate-500 dark:text-slate-400">
          {open ? 'Hide' : 'Show'}
        </span>
      </button>
      {open && (
        <div className="px-4 pb-4">
          <ul className="space-y-0">
            {shown.map((r, i) => (
              <RejectedRow key={i} rejection={r} />
            ))}
          </ul>
          {hiddenCount > 0 && (
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
              …and {hiddenCount} more not shown.
            </p>
          )}
        </div>
      )}
    </section>
  );
}
