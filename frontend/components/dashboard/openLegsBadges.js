/**
 * openLegsBadges — shared pure-render helpers for option-leg badges.
 *
 * Hosts the small set of badge / pill helpers that began life inline in
 * `OpenLegsCard.jsx`. Lifted out in #247 so a second callsite — the
 * per-position covered-call screen at `/positions/[id]/covered-call`
 * (`components/positions/CoveredCallView.jsx`) — can reuse them without
 * duplicating the visual contract. The helpers are byte-identical to their
 * original definitions; only the module location changed.
 *
 * Why this module lives in `components/dashboard/` (and not `positions/`):
 * `OpenLegsCard` is the original owner and consumer. The covered-call view
 * is the new importer. Hosting the shared helper under `positions/` would
 * make `dashboard/` reach across into a sibling feature directory it does
 * not own — a backward dependency. Keeping it in `dashboard/` keeps the
 * import direction forward (positions → dashboard, never the reverse).
 */

export const PILL_SHAPE = 'inline-block px-2 py-0.5 text-xs rounded-full';

// DTE-urgency thresholds (issue #248) — must stay in lockstep with the
// `compute_assignment_risk()` helper in
// `backend/app/services/dashboard_legs.py` (~line 137). Both use `<=` at the
// boundary, so DTE 7 is red and DTE 14 is amber. The frontend visual recipe
// and the backend risk classification share the same constants by intent.
export const DTE_RED_THRESHOLD = 7;
export const DTE_AMBER_THRESHOLD = 14;

// Tier label feeding both `dteBadgeClass` (color) and the row's
// `data-dte-urgency` attribute (the stable Playwright hook). Single source so
// the class and the data attribute cannot drift.
export function dteUrgencyTier(dte) {
  if (dte <= DTE_RED_THRESHOLD) return 'red';
  if (dte <= DTE_AMBER_THRESHOLD) return 'amber';
  return 'neutral';
}

export function dteBadgeClass(dte) {
  const tier = dteUrgencyTier(dte);
  if (tier === 'red') return 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300';
  if (tier === 'amber') return 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300';
  return 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-200';
}

/**
 * coverageBadge — the per-leg covered/naked pill (issue #246, spec §2).
 *
 * Pure render helper. `covered` → quiet emerald pill; `naked` → amber `⚠`
 * pill (the exact recipe `dteBadgeClass` uses at `dte <= 14`). Any other
 * value (`null`/undefined — a short put or a pre-#246 payload) renders
 * nothing. The badge is severity, not scan: it carries no `hidden lg:*` and
 * survives every breakpoint.
 *
 * `testIdPrefix` makes the badge's `data-testid` unambiguous when the same
 * helper is rendered at two callsites (row vs. InspectPanel echo). The
 * default keeps the existing row testid (`dashboard-leg-row-coverage`); the
 * InspectPanel passes a per-leg prefix so the echo is uniquely addressable
 * (`dashboard-leg-inspect-{leg.id}-coverage`).
 */
export function coverageBadge(coverage, { testIdPrefix = 'dashboard-leg-row' } = {}) {
  if (coverage === 'covered') {
    return (
      <span
        data-testid={`${testIdPrefix}-coverage`}
        data-coverage="covered"
        className={`${PILL_SHAPE} bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300`}
      >
        Covered
      </span>
    );
  }
  if (coverage === 'naked') {
    return (
      <span
        data-testid={`${testIdPrefix}-coverage`}
        data-coverage="naked"
        className={`${PILL_SHAPE} bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300`}
      >
        <span aria-hidden="true" className="mr-0.5">
          ⚠
        </span>
        Naked
      </span>
    );
  }
  return null;
}

/**
 * pnlDollarsText — the signed dollar-P&L line (issue #246, spec §3.2 / §3.5).
 *
 * Uses a LOCAL signed-currency formatter — `Intl`-based `formatCurrency()`
 * cannot emit the explicit `+` prefix the spec requires on gains, and the
 * explicit sign is an accessibility requirement (sign is not conveyed by
 * color alone). Gain → emerald `+$22.84`; loss → red `-$12.10`; zero or
 * unavailable (`null`/undefined — degraded path) → slate `—`.
 */
export function pnlDollarsText(pnl) {
  if (pnl == null || pnl === 0) {
    return (
      <span
        data-testid="dashboard-leg-row-pnl"
        data-pnl-sign="none"
        className="text-xs tabular-nums text-slate-400"
      >
        —
      </span>
    );
  }
  const isGain = pnl > 0;
  const text = isGain
    ? `+$${pnl.toFixed(2)}`
    : `-$${Math.abs(pnl).toFixed(2)}`;
  return (
    <span
      data-testid="dashboard-leg-row-pnl"
      data-pnl-sign={isGain ? 'gain' : 'loss'}
      className={`text-xs tabular-nums ${
        isGain
          ? 'text-emerald-600 dark:text-emerald-400'
          : 'text-red-600 dark:text-red-400'
      }`}
    >
      {text}
    </span>
  );
}
