import StatCard from '../common/StatCard';
import { formatCurrency, formatNumber, formatPercent } from '../../utils/formatters';

/**
 * KpiRow — four-tile portfolio summary above the decision row.
 *
 * Renders fallback `—` placeholders when values are null (e.g. Schwab
 * disconnected → no notional, no unrealized P/L). Per Q7 we always render
 * the unrealized P/L tile and substitute `—`; consistency over conditional
 * layout.
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

export default function KpiRow({ kpis }) {
  if (!kpis) return null;
  const breakdown = kpis.open_positions_breakdown || {};
  const positionSubtext = [
    breakdown.stock ? `${breakdown.stock} stock` : null,
    breakdown.csp ? `${breakdown.csp} CSP` : null,
    breakdown.cc ? `${breakdown.cc} CC` : null,
    breakdown.wheel ? `${breakdown.wheel} wheel` : null,
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

  return (
    <div
      data-testid="dashboard-kpi-row"
      className="grid grid-cols-2 md:grid-cols-4 gap-4"
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
    </div>
  );
}
