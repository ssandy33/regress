import StatCard from '../common/StatCard';
import { formatCurrency, formatPercent } from '../../utils/formatters';

/**
 * AccountSummaryRow — broker-reconciliation strip (v1.9.0, #420 + #421, PRD #415
 * R1/R2/R3/R4).
 *
 * Three tiles reconciling the dashboard to the connected Schwab account:
 *   - Account value (hero, emphasized) — Σ equity MV + option MV + cash (R1),
 *     with the breakdown as subtext and a `data-reconciles` flag. Renders the
 *     "Connect Schwab to reconcile" unavailable state until the broker balances
 *     resolve (#420).
 *   - Cash & sweep — sourced from the broker balance, never inferred (R2).
 *   - Day change — account-level signed $ / % (R3, #421), composed from the
 *     per-position equity day changes. Populated independently of the broker
 *     reconciliation: the tile lights up whenever `day_state === 'populated'`
 *     even while the account value / cash tiles are unavailable.
 *
 * States (design spec §States):
 *   - loading → 3 skeleton tiles.
 *   - unavailable (broker not connected → `summary.cash == null`) → account /
 *     cash tiles show `—` with a "Connect Schwab to reconcile" hint. Distinct
 *     from a false `$0`.
 *   - populated → figures + reconciliation badge.
 *
 * Reconcile badge (#429) — tri-state `summary.reconcile_state`, surfaced on the
 * account-value hero tile via `data-reconcile-state` (plus the back-compat
 * `data-reconciles`):
 *   - `reconciled` → quiet ✓ (the parity check passed on fresh broker data).
 *   - `unavailable` → muted "reconcile unavailable" — the broker net-liq is
 *     stale/disconnected and can't be confirmed right now. NOT alarming.
 *   - `mismatch` → the only alarming state (amber): a real discrepancy on
 *     fresh broker data.
 *
 * Grid: `grid-cols-2 lg:grid-cols-4`; Account value spans 2 cols (hero).
 */

function plColor(value) {
  if (value == null) return undefined;
  if (value > 0) return 'text-green-600 dark:text-green-400';
  if (value < 0) return 'text-red-600 dark:text-red-400';
  return undefined;
}

function ReconcileBadge({ state }) {
  if (state === 'reconciled') {
    return (
      <span
        data-reconcile-badge="reconciled"
        className="inline-flex items-center gap-1 text-xs text-green-600 dark:text-green-400 mt-1"
      >
        <span aria-hidden="true">✓</span> reconciled with broker
      </span>
    );
  }
  if (state === 'mismatch') {
    return (
      <span
        data-reconcile-badge="mismatch"
        className="inline-flex items-center gap-1 text-xs font-medium text-amber-600 dark:text-amber-400 mt-1"
      >
        <span aria-hidden="true">⚠</span> doesn&apos;t match broker
      </span>
    );
  }
  // unavailable — muted "can't confirm", never alarming.
  return (
    <span
      data-reconcile-badge="unavailable"
      className="inline-flex items-center gap-1 text-xs text-slate-400 dark:text-slate-500 mt-1"
    >
      reconcile unavailable
    </span>
  );
}

function signedCurrency(value) {
  if (value == null) return '—';
  return `${value > 0 ? '+' : ''}${formatCurrency(value)}`;
}

function SkeletonTile({ span }) {
  return (
    <div
      className={`bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-4 ${
        span || ''
      }`}
    >
      <div className="h-3 w-20 bg-slate-200 dark:bg-slate-700 rounded animate-pulse mb-2" />
      <div className="h-7 w-28 bg-slate-200 dark:bg-slate-700 rounded animate-pulse" />
    </div>
  );
}

export default function AccountSummaryRow({ summary, loading }) {
  if (loading) {
    return (
      <div
        data-testid="dashboard-account-summary"
        className="grid grid-cols-2 lg:grid-cols-4 gap-4"
        aria-busy="true"
      >
        <SkeletonTile span="col-span-2 lg:col-span-2" />
        <SkeletonTile />
        <SkeletonTile />
      </div>
    );
  }

  if (!summary) return null;

  // "Unavailable" (broker not connected): cash is null → render the connect
  // hint, NOT a false $0 that would assert a reconciled zero-cash account.
  const connected = summary.cash != null;

  const accountValue = connected ? formatCurrency(summary.account_value) : '—';
  const breakdown = connected
    ? `Equity ${formatCurrency(summary.equity_mv)} + Options ${signedCurrency(
        summary.option_mv
      )} + Cash ${formatCurrency(summary.cash)}`
    : 'Connect Schwab to reconcile';

  const cashValue = connected ? formatCurrency(summary.cash) : '—';

  // Reconcile verdict (#429) — tri-state. Only surfaced once the broker
  // balance resolves (connected); the disconnected strip already shows the
  // "Connect Schwab to reconcile" hint in the subtext.
  const reconcileState = summary.reconcile_state || 'unavailable';

  // Day change (#421 R3) — populated independently of broker reconciliation.
  const dayState = summary.day_state || 'no_prior_close';
  const dayPopulated = dayState === 'populated' && summary.day_change != null;
  const dayValue = dayPopulated
    ? `${signedCurrency(summary.day_change)} / ${
        summary.day_change_pct != null
          ? `${summary.day_change_pct > 0 ? '+' : ''}${formatPercent(summary.day_change_pct)}`
          : '—'
      }`
    : '—';
  const daySubtext = dayPopulated ? undefined : 'no prior close';

  return (
    <div
      data-testid="dashboard-account-summary"
      className="grid grid-cols-2 lg:grid-cols-4 gap-4"
    >
      {/* Account value hero — emphasis (blue ring + span) applied by the parent
          wrapper so the shared StatCard recipe stays intact (design spec).
          The reconcile badge is passed as the StatCard `footer` so it renders
          INSIDE the tile's bordered box rather than escaping below it (#436);
          `h-full` keeps the three tiles on one height baseline. */}
      <div className="col-span-2 lg:col-span-2 ring-1 ring-blue-500/40 rounded-lg h-full">
        <StatCard
          label="Account value"
          value={accountValue}
          subtext={breakdown}
          tooltip={connected ? breakdown : undefined}
          dataTestid="kpi-account-value"
          dataAttrs={{
            'data-reconciles': summary.reconciles ? 'true' : 'false',
            'data-reconcile-state': reconcileState,
          }}
          footer={connected ? <ReconcileBadge state={reconcileState} /> : null}
        />
      </div>
      <StatCard
        label="Cash & sweep"
        value={cashValue}
        subtext={connected ? undefined : 'from broker balance'}
        dataTestid="kpi-cash"
      />
      <StatCard
        label="Day change"
        value={dayValue}
        subtext={daySubtext}
        colorClass={dayPopulated ? plColor(summary.day_change) : undefined}
        dataTestid="kpi-day-change"
        dataAttrs={{ 'data-day-state': dayState }}
      />
    </div>
  );
}
