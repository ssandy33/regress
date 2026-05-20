// Composition surface for the populated covered-call view (issue #247).
//
// Renders:
//   - Two-card hero block: TodayCard + IfAssignedCard (equal-weight per
//     spec §3.2 / Q2).
//   - Per-leg breakdown table — read-only (no row click-through per Q3).
//   - "How these numbers are computed" formula block + Inputs line.
//
// The footer disclaimer is owned by CoveredCallPage (it renders for every
// state that has a payload, not just the populated one).
//
// Spec: frontend/design-specs/issue-247-combined-pnl-and-if-assigned.md §3.

import {
  coverageBadge,
  dteBadgeClass,
  pnlDollarsText,
} from '../dashboard/openLegsBadges';

// --- Number formatters ----------------------------------------------------

function formatDollar(value) {
  if (value === null || value === undefined) return '—';
  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : '';
  return `${sign}$${abs.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function formatSignedDollar(value) {
  if (value === null || value === undefined) return '—';
  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : '+';
  return `${sign}$${abs.toLocaleString(undefined, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

function valenceClass(value) {
  if (value === null || value === undefined) {
    return 'text-slate-400';
  }
  if (value > 0) return 'text-emerald-600 dark:text-emerald-400';
  if (value < 0) return 'text-red-600 dark:text-red-400';
  return 'text-slate-500 dark:text-slate-400';
}

function pnlSign(value) {
  if (value === null || value === undefined) return 'none';
  if (value > 0) return 'gain';
  if (value < 0) return 'loss';
  return 'none';
}

// --- TodayCard ------------------------------------------------------------

function TodayCard({ today }) {
  const combined = today?.combined_pnl;
  const heroText = combined === null || combined === undefined ? '—' : formatSignedDollar(combined);
  const heroValence = valenceClass(combined);
  const caption =
    combined === null || combined === undefined
      ? 'unrealized P&L unavailable'
      : 'combined net P&L';
  return (
    <div
      data-testid="covered-call-today-card"
      className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-5"
    >
      <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
        TODAY — UNREALIZED
      </div>
      <div
        data-testid="covered-call-today-hero"
        data-pnl-sign={pnlSign(combined)}
        className={`mt-3 text-4xl font-semibold tabular-nums ${heroValence}`}
      >
        {heroText}
      </div>
      <div className="text-sm text-slate-500 dark:text-slate-400">
        ({caption})
      </div>
      <div
        data-testid="covered-call-today-breakdown"
        className="mt-4 space-y-1 text-sm"
      >
        <div className="flex items-center justify-between">
          <span className="text-slate-600 dark:text-slate-300">Stock leg</span>
          <span className={`tabular-nums ${valenceClass(today?.stock_pnl)}`}>
            {today?.stock_pnl === null || today?.stock_pnl === undefined
              ? '—'
              : formatSignedDollar(today.stock_pnl)}
          </span>
        </div>
        <div className="flex items-center justify-between">
          <span className="text-slate-600 dark:text-slate-300">Option legs</span>
          <span className={`tabular-nums ${valenceClass(today?.options_pnl)}`}>
            {today?.options_pnl === null || today?.options_pnl === undefined
              ? '—'
              : formatSignedDollar(today.options_pnl)}
          </span>
        </div>
        <div className="border-t border-slate-200 dark:border-slate-700 pt-1 flex items-center justify-between font-medium">
          <span className="text-slate-700 dark:text-slate-200">Combined</span>
          <span className={`tabular-nums ${heroValence}`}>{heroText}</span>
        </div>
      </div>
      <p className="text-xs text-slate-500 dark:text-slate-400 mt-3">
        Scenario: no action taken, marked at the current option mid and
        current share price.
      </p>
    </div>
  );
}

// --- IfAssignedCard -------------------------------------------------------

function ifAssignedTotal(projections) {
  if (!projections || projections.length === 0) return null;
  const sum = projections.reduce((acc, p) => {
    if (p.if_assigned_pnl === null || p.if_assigned_pnl === undefined) {
      return acc;
    }
    return acc + p.if_assigned_pnl;
  }, 0);
  const allNull = projections.every(
    (p) => p.if_assigned_pnl === null || p.if_assigned_pnl === undefined,
  );
  return allNull ? null : Math.round(sum * 100) / 100;
}

function IfAssignedLegBlock({ projection, basis }) {
  const isSingle = projection.__single;
  const inner = (
    <>
      {!isSingle && (
        <div className="text-xs font-medium text-slate-500 dark:text-slate-400">
          ${projection.strike.toFixed(2)} call · {projection.qty}{' '}
          contract{projection.qty === 1 ? '' : 's'}
        </div>
      )}
      <div className="flex items-center justify-between">
        <span className="text-slate-600 dark:text-slate-300">
          Shares called
        </span>
        <span
          className={`tabular-nums ${valenceClass(projection.share_pnl)}`}
        >
          {formatSignedDollar(projection.share_pnl)}
        </span>
      </div>
      <div className="text-xs text-slate-500 dark:text-slate-400">
        at ${projection.strike.toFixed(2)} vs ${basis?.toFixed(2)} basis (
        {projection.shares_called} sh)
      </div>
      <div className="flex items-center justify-between">
        <span className="text-slate-600 dark:text-slate-300">
          Premium kept
        </span>
        <span
          className={`tabular-nums ${valenceClass(projection.premium_kept)}`}
        >
          {formatSignedDollar(projection.premium_kept)}
        </span>
      </div>
      <div className="border-t border-slate-200 dark:border-slate-700 pt-1 flex items-center justify-between font-medium">
        <span className="text-slate-700 dark:text-slate-200">If-assigned</span>
        <span
          className={`tabular-nums ${valenceClass(projection.if_assigned_pnl)}`}
        >
          {projection.if_assigned_pnl === null
            ? '—'
            : formatSignedDollar(projection.if_assigned_pnl)}
        </span>
      </div>
    </>
  );
  if (isSingle) {
    return <div className="mt-4 space-y-1 text-sm">{inner}</div>;
  }
  return (
    <div
      data-testid={`covered-call-if-assigned-leg-${projection.leg_id}`}
      data-leg-id={projection.leg_id}
      className="mt-4 space-y-1 text-sm border-t border-slate-200 dark:border-slate-700 pt-3 first:border-t-0 first:pt-0"
    >
      {inner}
    </div>
  );
}

function IfAssignedCard({ projections, basis }) {
  const total = ifAssignedTotal(projections);
  const heroText =
    total === null || total === undefined ? '—' : formatSignedDollar(total);
  const heroValence = valenceClass(total);
  const isMulti = projections.length > 1;
  // Single-leg layout matches the spec's hero caption "realized if {strike}C
  // exercised"; multi-leg drops the per-strike caption (each block carries
  // its own subhead).
  const heroCaption = isMulti
    ? 'realized if all open calls assigned'
    : projections.length === 1
      ? `realized if ${projections[0].strike.toFixed(0)}C exercised`
      : 'projected if-assigned';
  return (
    <div
      data-testid="covered-call-if-assigned-card"
      className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 p-5"
    >
      <div className="text-xs font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">
        IF ASSIGNED — PROJECTED
      </div>
      <div
        data-testid="covered-call-if-assigned-hero"
        data-pnl-sign={pnlSign(total)}
        className={`mt-3 text-4xl font-semibold tabular-nums ${heroValence}`}
      >
        {heroText}
      </div>
      <div className="text-sm text-slate-500 dark:text-slate-400">
        ({heroCaption})
      </div>
      {projections.map((p) => (
        <IfAssignedLegBlock
          key={p.leg_id}
          projection={isMulti ? p : { ...p, __single: true }}
          basis={basis}
        />
      ))}
      <p className="text-xs text-slate-500 dark:text-slate-400 mt-3">
        {isMulti
          ? 'Scenario: every open short call is assigned at expiration; shares are called away at each strike (earliest-expiring first), premium retained.'
          : projections.length === 1
            ? `Scenario: the short ${projections[0].strike.toFixed(0)}C is assigned at expiration; ${projections[0].shares_called} sh sold at $${projections[0].strike.toFixed(2)}, premium retained.`
            : 'Scenario: no open short call to project against.'}
      </p>
    </div>
  );
}

// --- PerLegBreakdownTable -------------------------------------------------

function PerLegBreakdownTable({ legs }) {
  if (!legs || legs.length === 0) return null;
  return (
    <div>
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400 mb-2">
        Per-leg breakdown
      </div>
      <div className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800 overflow-x-auto">
        <table
          data-testid="covered-call-leg-table"
          className="w-full text-sm"
        >
          <thead>
            <tr className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-slate-700">
              <th className="text-left font-medium py-2 px-3">Leg</th>
              <th className="text-left font-medium py-2 px-3">DTE</th>
              <th className="text-left font-medium py-2 px-3">Coverage</th>
              <th className="text-right font-medium py-2 px-3">Today P&amp;L</th>
              <th className="text-right font-medium py-2 px-3">If assigned</th>
            </tr>
          </thead>
          <tbody>
            {legs.map((leg) => {
              const letter = leg.type === 'put' ? 'P' : 'C';
              return (
                <tr
                  key={leg.leg_id}
                  data-testid="covered-call-leg-row"
                  data-leg-id={leg.leg_id}
                  className="border-b border-slate-100 dark:border-slate-700 last:border-b-0"
                >
                  <td className="py-2 px-3 font-medium text-slate-900 dark:text-white">
                    {leg.ticker} ${leg.strike.toFixed(2)} {letter}
                  </td>
                  <td className="py-2 px-3">
                    <span
                      className={`inline-block px-2 py-0.5 text-xs rounded-full ${dteBadgeClass(leg.dte)}`}
                    >
                      {leg.dte}d
                    </span>
                  </td>
                  <td className="py-2 px-3">
                    {coverageBadge(leg.coverage, {
                      testIdPrefix: `covered-call-leg-${leg.leg_id}`,
                    }) || (
                      <span className="text-slate-400">—</span>
                    )}
                  </td>
                  <td className="py-2 px-3 text-right">
                    {pnlDollarsText(leg.pnl_dollars)}
                  </td>
                  <td className="py-2 px-3 text-right tabular-nums">
                    {leg.if_assigned_pnl === null ||
                    leg.if_assigned_pnl === undefined ? (
                      <span className="text-slate-400">—</span>
                    ) : (
                      <span className={valenceClass(leg.if_assigned_pnl)}>
                        {formatSignedDollar(leg.if_assigned_pnl)}
                      </span>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// --- FormulasBlock --------------------------------------------------------

function FormulasBlock({ data }) {
  const pos = data.position;
  // Inputs line — keep figures behind a single line so the math is auditable.
  // Strike + credit + cost-to-close are dropped from the inputs line if the
  // position has no open call (the data is genuinely not there in that case).
  const firstCall = (data.if_assigned || [])[0];
  const firstLeg = (data.per_leg_breakdown || []).find(
    (lg) => lg.type === 'call',
  );
  const costToClose =
    firstLeg && firstLeg.pnl_dollars !== null && firstCall
      ? firstCall.premium_kept - firstLeg.pnl_dollars
      : null;
  const inputs = [
    `${pos.shares} sh`,
    `basis ${formatDollar(pos.broker_cost_basis)}`,
    pos.current_price !== null && pos.current_price !== undefined
      ? `current ${formatDollar(pos.current_price)}`
      : 'current —',
  ];
  if (firstCall) {
    inputs.push(`strike ${formatDollar(firstCall.strike)}`);
    inputs.push(`credit ${formatDollar(firstCall.premium_kept)}`);
    if (costToClose !== null) {
      inputs.push(`cost to close ${formatDollar(costToClose)}`);
    }
  }
  return (
    <div
      data-testid="covered-call-formulas"
      className="text-xs text-slate-500 dark:text-slate-400 font-mono space-y-1"
    >
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400 font-sans mb-1">
        How these numbers are computed
      </div>
      <div>· Stock leg P&amp;L = shares × (current price − broker cost basis)</div>
      <div>· Option leg P&amp;L = credit received − current cost to close</div>
      <div>· If-assigned = (strike − cost basis) × shares + premium retained</div>
      <div className="pt-2 font-sans">Inputs: {inputs.join(' · ')}.</div>
    </div>
  );
}

// --- CoveredCallView ------------------------------------------------------

export default function CoveredCallView({ data }) {
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <TodayCard today={data.combined_today} />
        <IfAssignedCard
          projections={data.if_assigned || []}
          basis={data.position?.broker_cost_basis}
        />
      </div>
      <PerLegBreakdownTable legs={data.per_leg_breakdown} />
      <FormulasBlock data={data} />
    </div>
  );
}
