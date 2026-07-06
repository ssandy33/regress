import { formatCurrency, formatPercent } from '../../utils/formatters';

/**
 * AccountSummaryRow — broker-reconciliation strip (v1.9.0, PRD #415 R1/R2/R3).
 *
 * Three tiles: Account value (hero, emphasized), Cash, and account-level Day
 * change. The Day-change tile (R3, #421) is fully populated from
 * ``summary.day_change`` / ``day_change_pct`` / ``day_state``. The Account value
 * and Cash tiles (R1/R2/R4) render their "Connect Schwab to reconcile"
 * unavailable state until the account-totals worker wires the broker balances —
 * ``summary.account_value`` / ``cash`` are ``null`` on the #421 spine.
 *
 * Tokens mirror ``common/StatCard`` (xs label, 2xl value, xs subtext). A local
 * ``Tile`` is used instead of ``StatCard`` so the frozen ``data-reconciles`` /
 * ``data-day-state`` attributes sit on the same node as the ``data-testid``.
 *
 * States: loading (3 skeleton tiles) | populated | unavailable (broker not
 * connected → ``—`` + a muted "Connect Schwab to reconcile" hint).
 */

function plColor(value) {
  if (value == null) return undefined;
  if (value > 0) return 'text-green-600 dark:text-green-400';
  if (value < 0) return 'text-red-600 dark:text-red-400';
  return undefined;
}

function signedCurrency(value) {
  if (value == null) return '—';
  return `${value > 0 ? '+' : ''}${formatCurrency(value)}`;
}

function signedPercent(value) {
  if (value == null) return null;
  return `${value > 0 ? '+' : ''}${formatPercent(value, 2)}`;
}

/**
 * Tile — StatCard-equivalent markup that also forwards arbitrary ``data-*``
 * attributes + the testid on the tile node. ``extraProps`` carries the frozen
 * ``data-reconciles`` / ``data-day-state`` attributes.
 */
function Tile({ label, value, subtext, colorClass, dataTestid, className = '', extraProps = {} }) {
  return (
    <div
      data-testid={dataTestid}
      className={`bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-4 ${className}`}
      {...extraProps}
    >
      <div className="text-xs text-slate-500 dark:text-slate-400 mb-1">{label}</div>
      <div
        className={`text-2xl font-semibold ${colorClass || 'text-slate-900 dark:text-white'}`}
      >
        {value}
      </div>
      {subtext && (
        <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">{subtext}</div>
      )}
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
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className={`${
              i === 0 ? 'col-span-2' : ''
            } h-24 animate-pulse rounded-lg bg-slate-200 dark:bg-slate-700`}
          />
        ))}
      </div>
    );
  }

  if (!summary) return null;

  const reconciles = summary.reconciles === true;
  const accountValue = summary.account_value;
  const cash = summary.cash;
  const dayChange = summary.day_change;
  const dayChangePct = summary.day_change_pct;
  const dayState = summary.day_state ?? 'no_prior_close';
  const brokerUnavailable = accountValue == null && cash == null;

  // Account value — hero tile. Reconciliation breakdown as subtext when the
  // broker balances are available; otherwise the connect hint.
  const valueSubtext = brokerUnavailable
    ? 'Connect Schwab to reconcile'
    : [
        summary.equity_mv != null ? `Equity ${formatCurrency(summary.equity_mv)}` : null,
        summary.option_mv != null ? `Options ${signedCurrency(summary.option_mv)}` : null,
        summary.cash != null ? `Cash ${formatCurrency(summary.cash)}` : null,
      ]
        .filter(Boolean)
        .join(' + ') || undefined;

  // Day change — the R3 tile this issue lands.
  const dayPopulated = dayState === 'populated';
  const dayValue = dayPopulated ? signedCurrency(dayChange) : '—';
  const dayColor = dayPopulated ? plColor(dayChange ?? dayChangePct) : undefined;
  const daySubtext = dayPopulated ? signedPercent(dayChangePct) || undefined : 'no prior close';

  return (
    <div
      data-testid="dashboard-account-summary"
      className="grid grid-cols-2 lg:grid-cols-4 gap-4"
    >
      <Tile
        label="Account value"
        value={accountValue == null ? '—' : formatCurrency(accountValue)}
        subtext={valueSubtext}
        dataTestid="kpi-account-value"
        className="col-span-2 lg:col-span-2 ring-1 ring-blue-500/40"
        extraProps={{ 'data-reconciles': reconciles ? 'true' : 'false' }}
      />
      <Tile
        label="Cash & sweep"
        value={cash == null ? '—' : formatCurrency(cash)}
        dataTestid="kpi-cash"
      />
      <Tile
        label="Day change"
        value={dayValue}
        subtext={daySubtext}
        colorClass={dayColor}
        dataTestid="kpi-day-change"
        extraProps={{ 'data-day-state': dayState }}
      />
    </div>
  );
}
