import Link from 'next/link';
import Card from '../common/Card';
import EmptyState from '../common/EmptyState';
import { formatPercent } from '../../utils/formatters';

/**
 * OpenLegsCard — triage-grade table of every open short option leg.
 *
 * V0.5 upgrade (issue #150 / spec §2.5 + §14.5):
 *   - %CAPTURED column — from `legs[].profit_target_status.captured_pct`.
 *     Renders `—` whenever `state === "unknown"` (universal V0.5 case
 *     because live option-chain data is deferred).
 *   - RISK column — from `legs[].assignment_risk` ("high" / "watch" / "low").
 *     "High" carries the ⛔ glyph for color-blind safety; all values are
 *     text-labeled so screen readers and grayscale users get the signal.
 *   - ACTION column — from `legs[].suggested_action` ("roll" / "hold" /
 *     "manage"). V0.5 never emits "close" because the underlying signal
 *     requires live option-chain data (see #146).
 *   - Earnings glyph (⚠) — rendered next to the expiration when
 *     `legs[].earnings_in_window === true`. Aria-labeled "Earnings before
 *     expiration" for screen readers.
 *
 * Responsive (spec §2.5):
 *   - Desktop (lg+): all columns visible.
 *   - Mobile (< lg): %CAPTURED and RISK hidden; ACTION rendered only when
 *     the value is "roll" or "manage" (the urgent cases).
 */

function dteBadgeClass(dte) {
  if (dte <= 7) return 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300';
  if (dte <= 14) return 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300';
  return 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-200';
}

function moneynessText(moneyness) {
  if (!moneyness) return <span className="text-slate-400">—</span>;
  if (moneyness.state === 'ITM') {
    return (
      <span className="text-red-600 dark:text-red-400">
        ITM ${moneyness.distance_dollars.toFixed(2)}
      </span>
    );
  }
  if (moneyness.state === 'ATM') {
    return <span className="text-yellow-600 dark:text-yellow-400">ATM</span>;
  }
  return (
    <span className="text-slate-600 dark:text-slate-300">
      OTM {formatPercent(moneyness.distance_pct, 1)}
    </span>
  );
}

function capturedText(status) {
  // Universal V0.5 rule (spec §14.5): render `—` whenever state is "unknown",
  // even if captured_pct happens to be non-null. The column ships as a
  // structural placeholder so the V0.7 live-chain work has somewhere to land.
  if (!status || status.state === 'unknown' || status.captured_pct == null) {
    return <span className="text-slate-400">—</span>;
  }
  return (
    <span className="tabular-nums text-slate-700 dark:text-slate-200">
      {Math.round(status.captured_pct * 100)}%
    </span>
  );
}

const RISK_VISUALS = {
  high: {
    label: 'High',
    glyph: '⛔',
    className: 'text-red-700 dark:text-red-300 font-medium',
  },
  watch: {
    label: 'Watch',
    glyph: '',
    className: 'text-yellow-700 dark:text-yellow-300 font-medium',
  },
  low: {
    label: 'Low',
    glyph: '',
    className: 'text-slate-600 dark:text-slate-300',
  },
};

function RiskCell({ risk }) {
  const visuals = RISK_VISUALS[risk] || RISK_VISUALS.low;
  return (
    <span className={visuals.className}>
      {visuals.glyph && (
        <span aria-hidden="true" className="mr-1">
          {visuals.glyph}
        </span>
      )}
      {visuals.label}
    </span>
  );
}

const ACTION_VISUALS = {
  roll: { label: 'Roll', className: 'text-red-700 dark:text-red-300 font-medium' },
  manage: { label: 'Manage', className: 'text-yellow-700 dark:text-yellow-300 font-medium' },
  hold: { label: 'Hold', className: 'text-slate-600 dark:text-slate-300' },
  // V0.5 never emits "close" per spec §14.5, but include for forward-compat.
  close: { label: 'Close target ✓', className: 'text-green-700 dark:text-green-300 font-medium' },
};

function ActionCell({ action, mobileOnlyUrgent }) {
  const visuals = ACTION_VISUALS[action] || ACTION_VISUALS.hold;
  const isUrgent = action === 'roll' || action === 'manage';
  // On mobile we hide non-urgent actions per spec §2.5. The `lg:!inline`
  // override forces the cell back on at the desktop breakpoint.
  const visibilityClass =
    mobileOnlyUrgent && !isUrgent ? 'hidden lg:inline' : 'inline';
  return <span className={`${visibilityClass} ${visuals.className}`}>{visuals.label}</span>;
}

function LegRow({ leg }) {
  return (
    <Link
      href={`/journal?position=${encodeURIComponent(leg.position_id)}`}
      data-testid="dashboard-leg-row"
      className="grid grid-cols-12 gap-2 items-center py-2 border-b border-slate-100 dark:border-slate-700 last:border-b-0 hover:bg-slate-50 dark:hover:bg-slate-700/50 px-2 -mx-2 rounded text-sm"
    >
      {/*
        Mobile (< lg): 12-col grid uses 2/2/3/2/3 for the 5 visible cells
        (ticker, strike, exp, dte, moneyness); %captured & risk are hidden;
        action wraps to a full-width row below when urgent.
        Desktop (lg+): 12-col grid uses 2/1/2/1/2/1/1/2 to fit 8 cells.
      */}
      <span className="col-span-2 lg:col-span-2 font-semibold text-slate-900 dark:text-white">
        {leg.ticker}
      </span>
      <span className="col-span-2 lg:col-span-1 tabular-nums text-slate-700 dark:text-slate-200">
        {leg.strike} {leg.type === 'put' ? 'P' : 'C'}
      </span>
      <span className="col-span-3 lg:col-span-2 tabular-nums text-slate-600 dark:text-slate-300 flex items-center gap-1">
        {leg.expiration}
        {leg.earnings_in_window === true && (
          <span
            data-testid="dashboard-leg-row-earnings"
            aria-label="Earnings before expiration"
            className="text-yellow-600 dark:text-yellow-400"
          >
            ⚠
          </span>
        )}
      </span>
      <span className="col-span-2 lg:col-span-1">
        <span
          className={`inline-block px-2 py-0.5 text-xs rounded-full ${dteBadgeClass(leg.dte)}`}
        >
          {leg.dte}d
        </span>
      </span>
      <span className="col-span-3 lg:col-span-2 truncate">
        {moneynessText(leg.moneyness)}
      </span>
      <span
        data-testid="dashboard-leg-row-captured"
        className="hidden lg:block lg:col-span-1 tabular-nums"
      >
        {capturedText(leg.profit_target_status)}
      </span>
      <span
        data-testid="dashboard-leg-row-risk"
        className="hidden lg:block lg:col-span-1"
      >
        <RiskCell risk={leg.assignment_risk} />
      </span>
      <span
        data-testid="dashboard-leg-row-action"
        className="col-span-12 lg:col-span-2 mt-1 lg:mt-0"
      >
        <ActionCell action={leg.suggested_action} mobileOnlyUrgent />
      </span>
    </Link>
  );
}

function HeaderRow() {
  return (
    <div className="grid grid-cols-12 gap-2 items-center px-2 -mx-2 pb-2 mb-1 text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-slate-700">
      <span className="col-span-2 lg:col-span-2">Ticker</span>
      <span className="col-span-2 lg:col-span-1">Strike</span>
      <span className="col-span-3 lg:col-span-2">Exp</span>
      <span className="col-span-2 lg:col-span-1">DTE</span>
      <span className="col-span-3 lg:col-span-2">Moneyness</span>
      <span className="hidden lg:block lg:col-span-1">% Capt</span>
      <span className="hidden lg:block lg:col-span-1">Risk</span>
      <span className="hidden lg:block lg:col-span-2">Action</span>
    </div>
  );
}

export default function OpenLegsCard({ legs, loading }) {
  if (loading) {
    return (
      <Card title="Open option legs" dataTestid="dashboard-legs-card">
        <div className="space-y-2" aria-busy="true">
          {[0, 1, 2, 3].map((i) => (
            <div
              key={i}
              className="h-7 animate-pulse rounded bg-slate-200 dark:bg-slate-700"
            />
          ))}
        </div>
      </Card>
    );
  }

  return (
    <Card
      title="Open option legs"
      dataTestid="dashboard-legs-card"
      footer={
        <Link
          href="/options"
          className="text-blue-600 dark:text-blue-400 hover:underline"
        >
          → View all in Options
        </Link>
      }
    >
      {legs?.length ? (
        <div>
          <HeaderRow />
          {legs.map((leg) => (
            <LegRow key={leg.id} leg={leg} />
          ))}
          <div className="text-xs text-slate-500 dark:text-slate-400 pt-3">
            Showing {legs.length} of {legs.length} open legs
          </div>
        </div>
      ) : (
        <EmptyState
          title="No open option legs"
          description="Sold puts and calls will appear here once you log a trade."
          primaryAction={{ label: 'Run scanner →', href: '/options' }}
        />
      )}
    </Card>
  );
}
