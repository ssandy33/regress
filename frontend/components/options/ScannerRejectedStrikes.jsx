// Rejected Strikes panel — humanized + sortable + summarized.
//
// Phase A (#190) introduced the human-sentence rendering of `human_reasons`.
// V1.0.8 (#257) layers three additive pieces on top:
//   1. Sort row above the list — three sort fields (strike / expiration /
//      failure_count). Default `failure_count_asc` (closest-to-passing first).
//      State component-local; no localStorage.
//   2. Per-rule summary band — one chip per non-zero rule family, count-desc
//      with canonical-order tie-break. Chip is a <button> (W-D's #258
//      popover anchors here — this issue ships an inert click target).
//   3. Near-pass badge — emerald "One rule away" pill on rows with
//      `rejection_reasons.length === 1`, replacing the right-aligned reason
//      count. Reason text uses a fact-led "Would pass — …" framing.
//
// The Card shell, the toggle button, the row test ID, and the
// `visibleCount=20` cap + tail are unchanged. #259 (W-E) will later wrap
// `RejectedRow` in a <details> for `rejection_reasons.length >= 3`.
//
// Source of truth for human sentences remains the backend's `human_reasons`
// field (populated by `backend/app/services/rejection_messages.py`); the
// CLIENT_COPY fallback below is purely defensive. Near-pass framing reads the
// raw `rejection_reasons` so it can extract the parameters (delta, OI, etc.).
//
// Specs:
//   - frontend/design-specs/issue-257-rejected-strikes-polish.md (V1.0.8)
//   - frontend/design-specs/scanner-education-v0.5.7.md (Affordance 4)

import { useMemo, useState } from 'react';

import {
  CANONICAL_RULE_ORDER,
  REJECTION_RULE_LABELS,
  extractRuleFamily,
  formatNearPassReason,
  labelForRuleFamily,
} from './scannerRejectionLabels';

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
  const code = extractRuleFamily(raw) || raw;
  return CLIENT_COPY_FALLBACK[code] || raw;
}

// Aggregate the rejected[] payload into a count per rule family. Per-strike
// dedupe inside `families` is defensive — a strike that emitted two
// `delta_out_of_range` codes (shouldn't happen, but be safe) still counts
// once toward `delta_out_of_range`. The summary answers "how many strikes
// were rejected by rule X," not "how many reason-strings mention X."
function summarizeRejections(rejected) {
  const counts = new Map();
  for (const r of rejected) {
    const families = new Set();
    for (const reason of r.rejection_reasons || []) {
      const family = extractRuleFamily(reason);
      if (family) families.add(family);
    }
    for (const f of families) {
      counts.set(f, (counts.get(f) || 0) + 1);
    }
  }
  // Count desc; ties broken by canonical rule order.
  return Array.from(counts.entries()).sort((a, b) => {
    if (b[1] !== a[1]) return b[1] - a[1];
    const aIdx = CANONICAL_RULE_ORDER.indexOf(a[0]);
    const bIdx = CANONICAL_RULE_ORDER.indexOf(b[0]);
    // Unknown families sort last; preserve relative order among unknowns.
    const aRank = aIdx === -1 ? Number.MAX_SAFE_INTEGER : aIdx;
    const bRank = bIdx === -1 ? Number.MAX_SAFE_INTEGER : bIdx;
    return aRank - bRank;
  });
}

function SortHeader({ field, label, sortField, sortDir, onSort }) {
  const active = sortField === field;
  const className = active
    ? 'text-xs font-medium text-slate-700 dark:text-slate-200 cursor-pointer select-none focus:outline-none focus:ring-2 focus:ring-blue-500 rounded'
    : 'text-xs font-medium text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200 cursor-pointer select-none focus:outline-none focus:ring-2 focus:ring-blue-500 rounded';
  return (
    <button
      type="button"
      data-testid={`scanner-rejected-strikes-sort-${field}`}
      onClick={() => onSort(field)}
      className={className}
    >
      {label}
      {active && (
        <span aria-hidden className="ml-0.5">
          {sortDir === 'asc' ? '↑' : '↓'}
        </span>
      )}
    </button>
  );
}

function SummaryChip({ family, count }) {
  const label = labelForRuleFamily(family);
  return (
    <button
      type="button"
      data-testid={`scanner-rejected-strikes-summary-rule-${family}`}
      data-count={count}
      className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs bg-slate-100 text-slate-700 dark:bg-slate-700/60 dark:text-slate-200 hover:bg-slate-200 dark:hover:bg-slate-600/60 focus:outline-none focus:ring-2 focus:ring-blue-500 cursor-pointer transition-colors"
    >
      <span>{label}</span>
      <span aria-hidden>&middot;</span>
      <span className="tabular-nums font-medium">{count}</span>
    </button>
  );
}

function NearPassBadge() {
  return (
    <span
      data-testid="scanner-rejected-strike-badge-near-pass"
      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300"
    >
      One rule away
    </span>
  );
}

function RejectedRow({ rejection }) {
  const rawReasons = rejection.rejection_reasons || [];
  const isNearPass = rawReasons.length === 1;

  // For normal/structural rows continue to prefer the backend's
  // human_reasons; fall back to the client-side humanization only when the
  // payload is empty (legacy / mis-deploy).
  const humanReasons =
    rejection.human_reasons && rejection.human_reasons.length > 0
      ? rejection.human_reasons
      : rawReasons.map(humanizeFallback);

  // For near-pass rows, render the fact-led "Would pass — …" sentence
  // computed from the raw rejection_reasons[0] (so we can extract the
  // observed value, the threshold, and the gap).
  const nearPassSentence = isNearPass
    ? formatNearPassReason(rawReasons[0]) || humanReasons[0]
    : null;

  return (
    <li
      data-testid="scanner-rejected-strike-row"
      className="py-2 border-b border-slate-100 dark:border-slate-700 last:border-0"
    >
      <div className="flex items-baseline justify-between gap-3 mb-1">
        <span className="text-sm font-medium text-slate-700 dark:text-slate-200">
          ${rejection.strike.toFixed(2)} {rejection.expiration}
        </span>
        {isNearPass ? (
          <NearPassBadge />
        ) : (
          <span className="text-xs text-slate-500 dark:text-slate-400">
            {humanReasons.length === 1
              ? '1 reason'
              : `${humanReasons.length} reasons`}
          </span>
        )}
      </div>
      {isNearPass ? (
        <p className="text-xs text-slate-600 dark:text-slate-300">
          {nearPassSentence}
        </p>
      ) : humanReasons.length === 1 ? (
        // Defensive branch — should only hit when rawReasons.length !== 1 but
        // humanReasons.length === 1 (legacy payload mismatch). Mirrors the
        // pre-V1.0.8 single-sentence rendering.
        <p className="text-xs text-slate-600 dark:text-slate-300">
          {humanReasons[0]}
        </p>
      ) : (
        <ul className="list-disc list-outside ml-5 space-y-0.5 text-xs text-slate-600 dark:text-slate-300">
          {humanReasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}
    </li>
  );
}

function compareRejections(a, b, field, dir) {
  let av;
  let bv;
  switch (field) {
    case 'strike':
      av = a.strike ?? 0;
      bv = b.strike ?? 0;
      break;
    case 'expiration':
      // ISO YYYY-MM-DD sorts lexicographically — no Date parse needed.
      av = a.expiration ?? '';
      bv = b.expiration ?? '';
      break;
    case 'failure_count':
    default:
      av = (a.rejection_reasons || []).length;
      bv = (b.rejection_reasons || []).length;
      break;
  }
  if (av < bv) return dir === 'asc' ? -1 : 1;
  if (av > bv) return dir === 'asc' ? 1 : -1;
  return 0;
}

export default function ScannerRejectedStrikes({
  rejected = [],
  defaultOpen = false,
  visibleCount = 20,
}) {
  const [open, setOpen] = useState(defaultOpen);
  const [sortField, setSortField] = useState('failure_count');
  const [sortDir, setSortDir] = useState('asc');

  const handleSort = (field) => {
    if (sortField === field) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDir('asc');
    }
  };

  // Summary aggregates the FULL payload — independent of sort and visibleCount.
  // The user's question "which rule is the binding constraint?" is about the
  // whole result set, not just the top 20.
  const summary = useMemo(() => summarizeRejections(rejected), [rejected]);

  // Sort is applied BEFORE the visibleCount slice — so the 20 rows we show
  // are the top 20 by current sort, not the first 20 in payload order.
  const sorted = useMemo(() => {
    const arr = [...rejected];
    arr.sort((a, b) => compareRejections(a, b, sortField, sortDir));
    return arr;
  }, [rejected, sortField, sortDir]);

  if (rejected.length === 0) return null;

  const shown = sorted.slice(0, visibleCount);
  const hiddenCount = sorted.length - shown.length;

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
        <>
          {/* Sort row */}
          <div className="flex items-center flex-wrap gap-3 px-4 pt-3 pb-2 text-xs border-t border-slate-100 dark:border-slate-700">
            <span className="text-slate-500 dark:text-slate-400">Sort by:</span>
            <SortHeader
              field="strike"
              label="Strike"
              sortField={sortField}
              sortDir={sortDir}
              onSort={handleSort}
            />
            <SortHeader
              field="expiration"
              label="Exp."
              sortField={sortField}
              sortDir={sortDir}
              onSort={handleSort}
            />
            <SortHeader
              field="failure_count"
              label="Failures"
              sortField={sortField}
              sortDir={sortDir}
              onSort={handleSort}
            />
          </div>

          {/* Summary band */}
          <div
            data-testid="scanner-rejected-strikes-summary"
            className="px-4 py-3 border-t border-slate-100 dark:border-slate-700 flex items-baseline flex-wrap gap-x-3 gap-y-2 text-xs"
          >
            <span className="text-slate-500 dark:text-slate-400 shrink-0">
              Of {rejected.length} rejected:
            </span>
            {summary.map(([family, count]) => (
              <SummaryChip key={family} family={family} count={count} />
            ))}
          </div>

          {/* Row list */}
          <div className="px-4 pb-4 border-t border-slate-100 dark:border-slate-700 pt-1">
            <ul className="space-y-0">
              {shown.map((r, i) => (
                <RejectedRow
                  key={`${r.strike}-${r.expiration}-${i}`}
                  rejection={r}
                />
              ))}
            </ul>
            {hiddenCount > 0 && (
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
                &hellip;and {hiddenCount} more not shown.
              </p>
            )}
          </div>
        </>
      )}
    </section>
  );
}

// Re-export the labels const for downstream consumers (e.g. W-D's relax
// popover). Keeps the import path single — callers can grab labels off the
// panel module without knowing about scannerRejectionLabels.js.
export { REJECTION_RULE_LABELS };
