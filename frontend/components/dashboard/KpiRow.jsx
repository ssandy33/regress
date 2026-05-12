import StatCard from '../common/StatCard';
import { formatCurrency, formatNumber, formatPercent } from '../../utils/formatters';

/**
 * KpiRow — seven-tile portfolio summary above the decision row.
 *
 * V0.5 extends the row from 4 to 7 tiles (issue #148):
 *   - Open positions, Notional value, Open legs, Unrealized P/L (existing)
 *   - Largest risk, Realized P/L (lifetime), Premium collected (lifetime) (new)
 *
 * Breakpoints per spec §14.2 (overrides §2.3): `grid-cols-2 md:grid-cols-3
 * lg:grid-cols-7`. The 7th tile spans 2 columns on mobile (`col-span-2`) to
 * avoid an orphan at the bottom of the 4×2 grid.
 *
 * Empty-state rules (spec §14.3):
 *   - Largest risk: `—` with tooltip (it's a pointer, not an aggregate)
 *   - Realized P/L: `$0` / `0%` (aggregate, mirrors Premium-collected)
 *   - Premium collected: `$0` / `0 trades`
 *
 * Payload-only fields (`kpis.premium_collected_ytd`, `kpis.largest_loser`)
 * ride in the payload for Next-Actions / analytics but are NOT rendered as
 * visible tiles in V0.5 — spec §14.4.
 */
function pctSubtext(pct, label) {
  if (pct == null) return null;
  const sign = pct > 0 ? '+' : '';
  return `${sign}${formatPercent(pct)} ${label}`;
}

function plColor(value) {
  if (value == null) return undefined;
  if (value > 0) return 'text-green-600 dark:text-green-400';
  if (value < 0) return 'text-red-600 dark:text-red-400';
  return undefined;
}

function signedCurrency(value) {
  if (value == null) return '—';
  return `${value >= 0 ? '+' : ''}${formatCurrency(value)}`;
}

export default function KpiRow({ kpis }) {
  if (!kpis) return null;
  const breakdown = kpis.open_positions_breakdown || {};
  // Issue #131 added the ``holding`` bucket — equity-only positions with no
  // open option legs. Order: csp -> cc -> wheel -> holding mirrors the
  // wheel lifecycle progression. ``stock`` remains for response-shape
  // stability; cleanup is tracked as a follow-up.
  const positionSubtext = [
    breakdown.stock ? `${breakdown.stock} stock` : null,
    breakdown.csp ? `${breakdown.csp} CSP` : null,
    breakdown.cc ? `${breakdown.cc} CC` : null,
    breakdown.wheel ? `${breakdown.wheel} wheel` : null,
    breakdown.holding ? `${breakdown.holding} holding` : null,
  ]
    .filter(Boolean)
    .join(' · ');

  const legBreakdown = kpis.open_legs_breakdown || {};
  const legSubtext = `${legBreakdown.puts ?? 0} puts · ${legBreakdown.calls ?? 0} calls`;

  const pl = kpis.unrealized_pl;
  const plDisplay =
    pl == null
      ? '—'
      : `${pl >= 0 ? '+' : ''}${formatCurrency(pl)}`;

  // Largest risk — pointer to the worst current loser; em-dash when none.
  const largestRisk = kpis.largest_risk;
  const largestRiskValue = largestRisk
    ? `${largestRisk.ticker} ${signedCurrency(largestRisk.unrealized_pl)}`
    : '—';
  const largestRiskSubtext = largestRisk
    ? pctSubtext(largestRisk.unrealized_pl_pct, 'on basis') || undefined
    : undefined;
  const largestRiskColor = largestRisk ? plColor(largestRisk.unrealized_pl) : undefined;

  // Realized P/L (lifetime) — aggregate; empty state is $0 / 0%.
  const realizedPl = kpis.realized_pl ?? 0;
  const realizedPlValue = signedCurrency(realizedPl);
  const realizedPlPct = kpis.realized_pl_pct;
  const realizedPlSubtext =
    realizedPlPct == null
      ? '0% lifetime'
      : `${realizedPlPct > 0 ? '+' : ''}${formatPercent(realizedPlPct)} lifetime`;

  // Premium collected (lifetime) — aggregate; empty state is $0 / 0 trades.
  const premiumTotal = kpis.premium_collected_total ?? 0;
  const premiumValue = `${premiumTotal >= 0 ? '+' : ''}${formatCurrency(premiumTotal)}`;
  const premiumTradesCount = kpis.premium_collected_trades ?? 0;
  const premiumSubtext = `${premiumTradesCount} trades`;

  return (
    <div
      data-testid="dashboard-kpi-row"
      className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-7 gap-4"
    >
      <StatCard
        label="Open positions"
        value={formatNumber(kpis.open_positions, 0)}
        subtext={positionSubtext || undefined}
        dataTestid="kpi-open-positions"
      />
      <StatCard
        label="Notional value"
        value={kpis.notional_value > 0 ? formatCurrency(kpis.notional_value) : '—'}
        subtext={pctSubtext(kpis.notional_change_pct, 'from cost') || undefined}
        dataTestid="kpi-notional"
      />
      <StatCard
        label="Open legs"
        value={formatNumber(kpis.open_legs, 0)}
        subtext={kpis.open_legs > 0 ? legSubtext : undefined}
        dataTestid="kpi-open-legs"
      />
      <StatCard
        label="Unrealized P/L"
        value={plDisplay}
        subtext={pctSubtext(kpis.unrealized_pl_pct, 'on basis') || undefined}
        colorClass={plColor(pl)}
        dataTestid="kpi-unrealized-pl"
      />
      <StatCard
        label="Largest risk"
        value={largestRiskValue}
        subtext={largestRiskSubtext}
        colorClass={largestRiskColor}
        tooltip="Position with the largest unrealized loss."
        dataTestid="kpi-largest-risk"
      />
      <StatCard
        label="Realized P/L"
        value={realizedPlValue}
        subtext={realizedPlSubtext}
        colorClass={plColor(realizedPl)}
        tooltip="Net P/L from closed positions and trades, lifetime."
        dataTestid="kpi-realized-pl"
      />
      {/*
        7th tile spans 2 columns on mobile (col-span-2) so it fills the
        bottom of the 2-col grid instead of leaving an orphan slot. At md+
        (3-col) and lg+ (7-col) it returns to a single column.
      */}
      <div className="col-span-2 md:col-span-1">
        <StatCard
          label="Premium collected"
          value={premiumValue}
          subtext={premiumSubtext}
          dataTestid="kpi-premium-lifetime"
        />
      </div>
    </div>
  );
}
