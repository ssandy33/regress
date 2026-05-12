import Link from 'next/link';
import Card from '../common/Card';
import EmptyState from '../common/EmptyState';
import { formatPercent } from '../../utils/formatters';

/**
 * UpcomingExpirationsCard — densified, three-line decision-oriented rows.
 *
 * V0.5 upgrade (issue #149 / spec §2.4 + §14.5):
 *   - Line 1 (identity + decision tag pill) — existing.
 *   - Line 2 (moneyness clause · premium remaining clause) — NEW.
 *     Premium-remaining renders `—` whenever
 *     `profit_target_status.state === "unknown"`, which is the universal
 *     V0.5 state because live option-chain integration is deferred.
 *   - Line 3 (earnings warning OR suggested action window) — NEW, conditional.
 *     Renders only when `earnings_in_window === true` OR DTE ≤ 7.
 *
 * Empty states (spec §2.4):
 *   - No open legs at all → "No open option legs" + "Run scanner →" CTA.
 *   - Open legs exist but none ≤ 14 DTE → "Nothing expiring in the next 14
 *     days" + secondary "View all open legs →" CTA.
 */

const TAG_PILL = {
  'roll-or-assign': 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  manage: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300',
  watch: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300',
  hold: 'bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-200',
};

const TAG_LABEL = {
  'roll-or-assign': 'Roll or assign',
  manage: 'Manage',
  watch: 'Watch',
  hold: 'Hold',
};

const TAG_ICON = {
  'roll-or-assign': '⚠',
  manage: '⚠',
  watch: '●',
  hold: '',
};

// Short weekday name for the suggested-window clause ("Roll by Wed close").
const WEEKDAYS_SHORT = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

function parseISODate(iso) {
  if (!iso) return null;
  const d = new Date(`${iso}T00:00:00`);
  return Number.isNaN(d.getTime()) ? null : d;
}

function formatShortDate(iso) {
  const d = parseISODate(iso);
  if (!d) return iso || '';
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${WEEKDAYS_SHORT[d.getDay()]} ${mm}/${dd}`;
}

function moneynessClause(moneyness) {
  if (!moneyness) return '—';
  if (moneyness.state === 'ITM') {
    return `ITM by $${moneyness.distance_dollars.toFixed(2)}`;
  }
  if (moneyness.state === 'ATM') {
    return 'At the money';
  }
  if (moneyness.state === 'OTM' && moneyness.distance_pct != null) {
    return `OTM ${formatPercent(moneyness.distance_pct, 1)}`;
  }
  return '—';
}

function premiumRemainingClause(status) {
  // Per spec §14.5 the V0.5 backend universally emits state === "unknown".
  // Frontend MUST render `—` whenever state is "unknown" regardless of
  // whether captured_pct happens to be non-null.
  if (!status || status.state === 'unknown') {
    return <span className="text-slate-400">Premium remaining —</span>;
  }
  const pctText =
    status.captured_pct == null
      ? ''
      : ` (${Math.round(status.captured_pct * 100)}% captured)`;
  return <span>Premium remaining{pctText}</span>;
}

function suggestedWindowText(dte) {
  // Lightweight V0.5 heuristic — the suggested-window clause renders only
  // when no earnings warning is present and DTE ≤ 7. A full options-chain
  // integration in V0.7 will replace this with a per-leg recommendation.
  if (dte <= 0) return 'Expires today';
  if (dte === 1) return 'Roll by tomorrow close';
  if (dte <= 3) return 'Roll within the next 1–2 sessions';
  return 'Roll by mid-week close';
}

function ExpirationRow({ leg }) {
  const tag = leg.decision_tag;
  const earningsActive = leg.earnings_in_window === true;
  const shortDte = leg.dte <= 7;
  // Line 3 renders only when earnings flag is set OR DTE ≤ 7 (spec §2.4).
  const showLine3 = earningsActive || shortDte;
  const showEarningsLine = earningsActive;

  return (
    <Link
      href={`/journal?position=${encodeURIComponent(leg.position_id)}`}
      data-testid="dashboard-expiration-row"
      className="block py-3 border-b border-slate-100 dark:border-slate-700 last:border-b-0 hover:bg-slate-50 dark:hover:bg-slate-700/50 px-2 -mx-2 rounded"
    >
      {/* Line 1 — identity + decision tag pill (right-aligned). */}
      <div className="flex items-baseline justify-between gap-2">
        <div className="flex items-baseline gap-2">
          {TAG_ICON[tag] && (
            <span
              className={
                tag === 'roll-or-assign' || tag === 'manage'
                  ? 'text-red-500'
                  : 'text-yellow-500'
              }
              aria-hidden="true"
            >
              {TAG_ICON[tag]}
            </span>
          )}
          <span className="font-semibold text-slate-900 dark:text-white">
            {leg.ticker} {leg.strike} {leg.type === 'put' ? 'P' : 'C'}
          </span>
          <span className="text-sm text-slate-500 dark:text-slate-400">
            {leg.expiration} · {leg.dte}d
          </span>
        </div>
        <span
          className={`inline-block px-2 py-0.5 text-xs rounded-full ${TAG_PILL[tag] || ''}`}
        >
          {TAG_LABEL[tag] || tag}
        </span>
      </div>
      {/* Line 2 — moneyness clause · premium remaining clause. */}
      <div className="mt-1 text-sm text-slate-600 dark:text-slate-300 flex flex-wrap items-baseline gap-x-2">
        <span>{moneynessClause(leg.moneyness)}</span>
        <span className="text-slate-300 dark:text-slate-600" aria-hidden="true">
          ·
        </span>
        <span>{premiumRemainingClause(leg.profit_target_status)}</span>
      </div>
      {/* Line 3 (conditional) — earnings warning OR suggested-window text. */}
      {showLine3 && (
        <div
          data-testid="dashboard-expiration-row-earnings"
          className="mt-1 text-sm text-slate-600 dark:text-slate-300"
        >
          {showEarningsLine ? (
            <span className="text-yellow-700 dark:text-yellow-300">
              <span aria-hidden="true">⚠ </span>
              Earnings {formatShortDate(leg.expiration)} — roll past or close
              before
            </span>
          ) : (
            <span className="text-slate-700 dark:text-slate-200">
              {suggestedWindowText(leg.dte)}
            </span>
          )}
        </div>
      )}
    </Link>
  );
}

export default function UpcomingExpirationsCard({
  expirations,
  loading,
  openLegsCount,
}) {
  if (loading) {
    return (
      <Card title="Upcoming expirations" description="Next 14 days" dataTestid="dashboard-expirations-card">
        <div className="space-y-3" aria-busy="true">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-16 animate-pulse rounded bg-slate-200 dark:bg-slate-700"
            />
          ))}
        </div>
      </Card>
    );
  }

  const hasOpenLegs = (openLegsCount ?? 0) > 0;
  const hasExpirations = expirations?.length > 0;

  return (
    <Card
      title="Upcoming expirations"
      description="Next 14 days"
      dataTestid="dashboard-expirations-card"
      footer={
        <Link
          href="/journal"
          className="text-blue-600 dark:text-blue-400 hover:underline"
        >
          → Manage in Journal
        </Link>
      }
    >
      {hasExpirations ? (
        <div>
          {expirations.map((leg) => (
            <ExpirationRow key={leg.id} leg={leg} />
          ))}
        </div>
      ) : hasOpenLegs ? (
        <EmptyState
          title="Nothing expiring in the next 14 days"
          description="Open legs further out are still listed below."
          dataTestid="dashboard-expirations-empty-no-near"
        />
      ) : (
        <EmptyState
          title="No open option legs"
          description="Sold puts and calls will appear here once you log a trade."
          primaryAction={{ label: 'Run scanner →', href: '/options' }}
          dataTestid="dashboard-expirations-empty-no-legs"
        />
      )}
    </Card>
  );
}
