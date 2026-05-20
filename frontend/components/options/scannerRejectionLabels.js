// Single source of truth for human labels and near-pass framing for the
// options-scanner Rejected Strikes panel.
//
// `REJECTION_RULE_LABELS` is the const map V1.0.8 pins as the canonical human
// label per rule family — used by the summary-band chips in
// `ScannerRejectedStrikes.jsx` and (post-merge) by W-D's relax-popover so the
// two surfaces agree on label text.
//
// `formatNearPassReason(raw)` reads a raw rejection-reason string (the same
// machine-parseable form produced by `app/services/rejection_messages.py`'s
// regexes) and returns a fact-led near-pass sentence — the pattern is
// `"Would pass — {observed} {operator} {threshold} ({gap})."` per design spec
// §4.2.B. Binary rules (`itm_put`, `zero_bid`) get a `(binary: this rule has no
// relax threshold)` suffix. Unknown / unparseable codes fall back to the raw
// string unchanged — defensive, never crash.
//
// Spec: frontend/design-specs/issue-257-rejected-strikes-polish.md (§3.4, §4.2)

export const REJECTION_RULE_LABELS = {
  fails_10pct_rule: 'Distance from basis',
  below_cost_basis: 'Cost basis',
  itm_put: 'In-the-money',
  delta_out_of_range: 'Delta',
  low_open_interest: 'Open interest',
  zero_bid: 'Zero bid',
  wide_bid_ask_spread: 'Spread',
  return_below_target: 'Return below target',
  return_above_cap: 'Return above cap',
  iv_rank_below_floor: 'IV rank',
};

// Canonical rule order — matches the order `_check_rejection` appends to
// `reasons` in `backend/app/services/options_scanner.py`. Used to break ties
// when two rule families have identical reject counts.
export const CANONICAL_RULE_ORDER = [
  'fails_10pct_rule',
  'below_cost_basis',
  'itm_put',
  'delta_out_of_range',
  'low_open_interest',
  'zero_bid',
  'wide_bid_ask_spread',
  'return_below_target',
  'return_above_cap',
  'iv_rank_below_floor',
];

// Extract the rule family — the prefix up to the first colon — from a raw
// rejection-reason string. Mirrors the existing `humanizeFallback` regex at
// `ScannerRejectedStrikes.jsx:39` so the summary aggregator and the per-row
// fallback agree.
export function extractRuleFamily(raw) {
  if (!raw) return null;
  const match = /^([a-z_]+)/i.exec(raw);
  return match ? match[1] : null;
}

// Human-friendly fallback label for an unknown rule family. Should never
// surface in practice (the const map above covers every family the scanner
// emits) — this is purely defensive against a stale UI / new backend rule.
export function fallbackRuleLabel(family) {
  if (!family) return 'Unknown';
  const spaced = family.replace(/_/g, ' ');
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export function labelForRuleFamily(family) {
  return REJECTION_RULE_LABELS[family] || fallbackRuleLabel(family);
}

// ---------------------------------------------------------------------------
// Near-pass framing — per-family regex parsers.
// ---------------------------------------------------------------------------
//
// Each parser reads the same f-string shape produced by `options_scanner.py`'s
// `_check_rejection` and `rejection_messages.py`'s regexes, extracts the
// numbers, and renders a fact-led "Would pass — …" sentence with an explicit
// gap parenthetical so the user can see at a glance how close they are.
//
// Pattern: `Would pass — {observed} {operator} {threshold} ({gap}).`

const NEAR_PASS_REGEXES = {
  fails_10pct_rule: /^fails_10pct_rule:\s*strike\s*(-?\d+(?:\.\d+)?)%\s*above basis,\s*requires\s*(-?\d+(?:\.\d+)?)%/i,
  below_cost_basis: /^below_cost_basis:\s*strike\s*\$(-?\d+(?:\.\d+)?)\s*<\s*floor\s*\$(-?\d+(?:\.\d+)?)/i,
  itm_put: /^itm_put:\s*strike\s*\$(-?\d+(?:\.\d+)?)\s*>\s*price\s*\$(-?\d+(?:\.\d+)?)/i,
  delta_out_of_range: /^delta_out_of_range:\s*\|(-?\d+(?:\.\d+)?)\|\s*not in\s*\[(-?\d+(?:\.\d+)?),\s*(-?\d+(?:\.\d+)?)\]/i,
  low_open_interest: /^low_open_interest:\s*(-?\d+)\s*<\s*(-?\d+)/i,
  return_below_target: /^return_below_target:\s*(-?\d+(?:\.\d+)?)%\s*<\s*(-?\d+(?:\.\d+)?)%/i,
  return_above_cap: /^return_above_cap:\s*(-?\d+(?:\.\d+)?)%\s*>\s*(-?\d+(?:\.\d+)?)%/i,
  wide_bid_ask_spread: /^wide_bid_ask_spread:\s*(-?\d+(?:\.\d+)?)%\s*>\s*(-?\d+(?:\.\d+)?)%/i,
  iv_rank_below_floor: /^iv_rank_below_floor:\s*(-?\d+(?:\.\d+)?)\s*<\s*(-?\d+(?:\.\d+)?)/i,
};

// Format a percentage gap with pp ("percentage points") suffix.
function fmtPp(value, decimals = 2) {
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return `${n.toFixed(decimals)}pp`;
}

function fmtPct(value, decimals = 1) {
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return `${n.toFixed(decimals)}%`;
}

function fmtDollars(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return String(value);
  return `$${n.toFixed(2)}`;
}

function nearPassFails10pct(match) {
  const pct = parseFloat(match[1]);
  const requires = parseFloat(match[2]);
  const gap = requires - pct;
  return `Would pass — strike is ${pct.toFixed(1)}% above basis, your ${requires.toFixed(1)}% rule requires ${requires.toFixed(1)}% (${fmtPp(gap, 1)} short).`;
}

function nearPassBelowCostBasis(match) {
  const strike = parseFloat(match[1]);
  const floor = parseFloat(match[2]);
  const gap = floor - strike;
  return `Would pass — strike ${fmtDollars(strike)} is below your ${fmtDollars(floor)} floor (${fmtDollars(gap)} short).`;
}

function nearPassItmPut(match) {
  const strike = parseFloat(match[1]);
  const price = parseFloat(match[2]);
  return `Would pass — strike ${fmtDollars(strike)} is above current price ${fmtDollars(price)} (binary: this rule has no relax threshold).`;
}

function nearPassDelta(match) {
  const delta = parseFloat(match[1]);
  const minDelta = parseFloat(match[2]);
  const maxDelta = parseFloat(match[3]);
  const absDelta = Math.abs(delta);
  let gap;
  if (absDelta > maxDelta) {
    gap = absDelta - maxDelta;
    return `Would pass — delta ${delta.toFixed(2)} is outside your ${minDelta.toFixed(2)}–${maxDelta.toFixed(2)} range (${gap.toFixed(2)} over).`;
  }
  if (absDelta < minDelta) {
    gap = minDelta - absDelta;
    return `Would pass — delta ${delta.toFixed(2)} is outside your ${minDelta.toFixed(2)}–${maxDelta.toFixed(2)} range (${gap.toFixed(2)} short).`;
  }
  // Defensive — shouldn't happen if scanner emitted this code.
  return `Would pass — delta ${delta.toFixed(2)} is outside your ${minDelta.toFixed(2)}–${maxDelta.toFixed(2)} range.`;
}

function nearPassLowOi(match) {
  const oi = parseInt(match[1], 10);
  const minOi = parseInt(match[2], 10);
  const gap = minOi - oi;
  return `Would pass — open interest ${oi} is below your ${minOi} minimum (${gap} short).`;
}

function nearPassReturnBelow(match) {
  const pct = parseFloat(match[1]);
  const minPct = parseFloat(match[2]);
  const gap = minPct - pct;
  return `Would pass — return ${fmtPct(pct, 2)} is below your ${fmtPct(minPct, 1)} target (${fmtPp(gap, 2)} short).`;
}

function nearPassReturnAbove(match) {
  const pct = parseFloat(match[1]);
  const maxPct = parseFloat(match[2]);
  const gap = pct - maxPct;
  return `Would pass — return ${fmtPct(pct, 2)} is above your ${fmtPct(maxPct, 1)} cap (${fmtPp(gap, 2)} over).`;
}

function nearPassWideSpread(match) {
  const pct = parseFloat(match[1]);
  const maxPct = parseFloat(match[2]);
  const gap = pct - maxPct;
  return `Would pass — spread ${fmtPct(pct, 1)} is above your ${fmtPct(maxPct, 1)} cap (${fmtPp(gap, 1)} over).`;
}

function nearPassIvRank(match) {
  const rank = parseFloat(match[1]);
  const minRank = parseFloat(match[2]);
  const gap = minRank - rank;
  return `Would pass — IV rank ${rank.toFixed(0)} is below your ${minRank.toFixed(0)} floor (${gap.toFixed(0)} short).`;
}

const NEAR_PASS_FORMATTERS = {
  fails_10pct_rule: nearPassFails10pct,
  below_cost_basis: nearPassBelowCostBasis,
  itm_put: nearPassItmPut,
  delta_out_of_range: nearPassDelta,
  low_open_interest: nearPassLowOi,
  return_below_target: nearPassReturnBelow,
  return_above_cap: nearPassReturnAbove,
  wide_bid_ask_spread: nearPassWideSpread,
  iv_rank_below_floor: nearPassIvRank,
};

// `zero_bid` is a literal code (no parameters) — handled out-of-band.
const ZERO_BID_NEAR_PASS =
  'Would pass — but no buyer is showing a bid (binary: this rule has no relax threshold).';

/**
 * Format a single raw rejection-reason string as a fact-led near-pass sentence.
 *
 * Pattern: `Would pass — {observed} {operator} {threshold} ({gap}).` Binary
 * rules (`itm_put`, `zero_bid`) get a `(binary: this rule has no relax
 * threshold)` suffix. Unknown / unparseable codes fall back to the raw string
 * unchanged so we never blank the user out.
 *
 * @param {string} raw - The raw rejection-reason string (e.g.
 *   `"delta_out_of_range: |0.38| not in [0.20, 0.35]"`).
 * @returns {string} A near-pass framed sentence, or the raw string unchanged.
 */
export function formatNearPassReason(raw) {
  if (!raw || typeof raw !== 'string') return String(raw ?? '');
  const trimmed = raw.trim();

  // Special-case zero_bid (literal code, no parameters).
  if (trimmed === 'zero_bid' || trimmed.startsWith('zero_bid:')) {
    return ZERO_BID_NEAR_PASS;
  }

  const family = extractRuleFamily(trimmed);
  if (!family) return raw;

  const re = NEAR_PASS_REGEXES[family];
  const formatter = NEAR_PASS_FORMATTERS[family];
  if (!re || !formatter) return raw;

  const match = re.exec(trimmed);
  if (!match) return raw;

  try {
    return formatter(match);
  } catch {
    // Defensive — never crash; show the raw string.
    return raw;
  }
}
