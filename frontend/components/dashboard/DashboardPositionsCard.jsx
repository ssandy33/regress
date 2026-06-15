import Link from 'next/link';
import Card from '../common/Card';
import EmptyState from '../common/EmptyState';
import { formatCurrency, formatPercent } from '../../utils/formatters';

/**
 * DashboardPositionsCard — triage table (issue #151).
 *
 * Per-position fields are sourced from the V0.5 backend payload (#146):
 * ``positions[].wheel_status``, ``positions[].next_suggested_action``,
 * ``positions[].pl_pct``, ``positions[].broker_cost_basis``.
 *
 * Day column rule (spec §14.6): ``positions[].day_change`` is NOT in the
 * V0.5 backend payload. We render the column header and ``—`` in every cell
 * on desktop so the layout stays stable when V0.7 ships the data. The column
 * is hidden entirely on mobile (< 1024px), where the table is already wide.
 *
 * Responsive strategy: single table, single set of rows. Columns that hide
 * on mobile (``P/L $`` and ``Day``) use ``hidden lg:table-cell`` so the
 * cells don't ship to small viewports. The Cost-basis cell switches between
 * dual-line (desktop) and adjusted-only (mobile) via inline CSS classes.
 * One table = one ``dashboard-position-row`` per position, no DOM duplication.
 *
 * Cell-level links (spec §2.6 / Q7): the ticker and next-action cells are
 * the only interactive targets in each row. The rest of the row is
 * non-interactive but hover-highlights, so the per-row action link doesn't
 * compete with a row-wide click target.
 */

function plClass(value) {
  if (value == null) return '';
  if (value > 0) return 'text-green-600 dark:text-green-400';
  if (value < 0) return 'text-red-600 dark:text-red-400';
  return '';
}

/**
 * Visual treatment for the wheel-status pill. Text label is the source of
 * truth (color is reinforcement) per spec §2.6 / §7 accessibility note.
 */
const STATUS_PILL_CLASSES = {
  CSP: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  CC: 'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
  Wheel: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300',
  Holding: 'bg-slate-100 text-slate-700 dark:bg-slate-700 dark:text-slate-200',
};

const STATUS_TOOLTIPS = {
  CSP: 'Cash-secured put cycle — collecting premium on the put side.',
  CC: 'Covered call open on this position.',
  Wheel: 'Both put history and a current call — full wheel cycle.',
  Holding: 'Stock held with no open option legs.',
};

/**
 * Map a backend ``next_suggested_action`` label to a per-row CTA.
 *
 * Returns ``null`` when the action is "hold" or unknown — those cells
 * render as plain "Hold" / "—" text. The label vocabulary is locked by
 * ``_NEXT_ACTION_TABLE_LABEL`` in ``backend/app/services/dashboard.py``.
 */
function nextActionCta(action, ticker, positionId) {
  if (!action || action === 'hold') return null;
  switch (action) {
    case 'Cover':
      return {
        label: 'Cover',
        href: `/options?ticker=${encodeURIComponent(ticker)}`,
      };
    case 'Review':
      // Issue #280: Review CTA routes to the per-position Stock Research
      // page, not the journal. The other two actions in this branch
      // continue to land in the ledger.
      return {
        label: action,
        href: `/positions/${encodeURIComponent(positionId)}/review`,
      };
    case 'Roll':
    case 'Manage':
      return {
        label: action,
        href: `/journal?position=${encodeURIComponent(positionId)}`,
      };
    case 'Reconnect':
    case 'Renew token':
      return { label: action, href: '/settings#schwab' };
    case 'Refresh data':
      // Inline action on Next Actions section; in the row cell we link to
      // settings as a sensible fallback target.
      return { label: action, href: '/settings' };
    case 'Run scanner':
      return { label: action, href: '/options' };
    default:
      // Unknown label — render the raw label as plain text so screen readers
      // still see it but no link is created.
      return null;
  }
}

function CostBasisCell({ position }) {
  // CSP-only rows (zero shares) have no broker basis; the legacy "cash-secured"
  // copy still reads more clearly than a bare em-dash.
  const cspOnly = (position.shares ?? 0) === 0;
  if (cspOnly) {
    return (
      <span className="text-slate-700 dark:text-slate-200">cash-secured</span>
    );
  }
  // Issue #320: per-share basis (with a muted /sh affordance) so this cell
  // aligns 1:1 with the per-share Current column. The currency number keeps
  // tabular-nums; /sh and adj. are muted non-tabular suffixes. Backend sends
  // null when shares == 0, but the cspOnly branch above already short-circuits
  // those rows, so null here only happens on incomplete data → em-dash.
  const broker = position.broker_cost_basis_per_share;
  const adjusted = position.adjusted_cost_basis_per_share;
  return (
    <div className="flex flex-col items-end">
      {/*
        Desktop: dual-line broker (line 1) + adjusted (line 2, muted).
        Mobile: only the adjusted-basis line is visible. Both values stay
        in the DOM so screen readers read broker then adjusted on desktop
        (AC: "semantic markup so screen readers read both").
      */}
      <span
        className="hidden lg:inline text-slate-900 dark:text-white"
        data-testid="dashboard-position-broker-basis"
      >
        {broker == null ? (
          '—'
        ) : (
          <>
            <span className="tabular-nums">{formatCurrency(broker)}</span>
            <span className="text-xs text-slate-400 dark:text-slate-500 ml-1">/sh</span>
          </>
        )}
      </span>
      <span
        className="text-xs lg:text-xs text-slate-500 dark:text-slate-400"
        data-testid="dashboard-position-adjusted-basis"
      >
        {adjusted == null ? (
          '—'
        ) : (
          <>
            <span className="lg:hidden text-sm text-slate-700 dark:text-slate-200">
              <span className="tabular-nums">{formatCurrency(adjusted)}</span>
              <span className="text-xs text-slate-400 dark:text-slate-500 ml-1">/sh</span>
            </span>
            <span className="hidden lg:inline">
              <span className="tabular-nums">{formatCurrency(adjusted)}</span>
              <span className="text-xs text-slate-400 dark:text-slate-500 ml-1">/sh adj.</span>
            </span>
          </>
        )}
      </span>
    </div>
  );
}

function StatusPill({ status }) {
  const pillClass = STATUS_PILL_CLASSES[status] || STATUS_PILL_CLASSES.Holding;
  const tooltip = STATUS_TOOLTIPS[status] || '';
  return (
    <span
      data-testid="dashboard-position-status"
      title={tooltip}
      className={`inline-block px-2 py-0.5 text-xs rounded-full ${pillClass}`}
    >
      {status || 'Holding'}
    </span>
  );
}

/**
 * The secondary `Covered call view →` link (#247, Q4 option b).
 *
 * Lives in the same cell as the rule-driven `next_suggested_action` CTA,
 * stacked below it. Only renders for positions that have shares AND a
 * wheel_status of CC or Wheel — both indicate at least one open short call
 * against the position, which is the precondition for the combined-P&L
 * screen being meaningful. A Holding row with shares but no short call
 * intentionally does NOT show the link (the screen would resolve to the
 * `no-short-call` empty state, which is not where we want the user to land).
 */
function CoveredCallLink({ position }) {
  const status = position?.wheel_status;
  const shares = position?.shares ?? 0;
  if (shares <= 0) return null;
  if (status !== 'CC' && status !== 'Wheel') return null;
  return (
    <Link
      href={`/positions/${encodeURIComponent(position.id)}/covered-call`}
      data-testid="dashboard-position-covered-call-link"
      className="block text-xs text-blue-600 dark:text-blue-400 hover:underline mt-1"
    >
      Covered call view
      <span aria-hidden="true"> →</span>
    </Link>
  );
}

function NextActionCell({ position }) {
  const action = position.next_suggested_action;
  const cta = nextActionCta(action, position.ticker, position.id);
  const primary = !cta ? (
    <span
      data-testid="dashboard-position-next-action"
      className="text-slate-500 dark:text-slate-400"
    >
      {action === 'hold' || !action ? 'Hold' : action}
    </span>
  ) : (
    <Link
      href={cta.href}
      data-testid="dashboard-position-next-action"
      className="text-blue-600 dark:text-blue-400 hover:underline"
    >
      {cta.label}
      <span aria-hidden="true"> →</span>
    </Link>
  );
  return (
    <div className="flex flex-col items-end">
      {primary}
      <CoveredCallLink position={position} />
    </div>
  );
}

function PctPlCell({ value }) {
  if (value == null) {
    return <span className="text-slate-500 dark:text-slate-400">—</span>;
  }
  const sign = value > 0 ? '+' : '';
  return (
    <span className={`tabular-nums ${plClass(value)}`}>
      {sign}
      {formatPercent(value, 2)}
    </span>
  );
}

function PositionRow({ position }) {
  return (
    <tr
      data-testid="dashboard-position-row"
      className="border-b border-slate-100 dark:border-slate-700 last:border-b-0 hover:bg-slate-50 dark:hover:bg-slate-700/50"
    >
      <td className="py-2 px-3 font-semibold text-slate-900 dark:text-white">
        <Link
          href={`/journal?position=${encodeURIComponent(position.id)}`}
          className="hover:underline"
        >
          {position.ticker}
        </Link>
      </td>
      <td className="py-2 px-3 text-right tabular-nums text-slate-700 dark:text-slate-200">
        {(position.shares ?? 0) === 0 ? '—' : position.shares}
      </td>
      <td className="py-2 px-3 text-right">
        <CostBasisCell position={position} />
      </td>
      <td className="py-2 px-3 text-right tabular-nums text-slate-700 dark:text-slate-200">
        {position.current_price == null ? '—' : formatCurrency(position.current_price)}
      </td>
      <td className="py-2 px-3 text-right">
        <PctPlCell value={position.pl_pct} />
      </td>
      {/* P/L $ — hidden on mobile (spec §2.6 mobile column table) */}
      <td
        className={`hidden lg:table-cell py-2 px-3 text-right tabular-nums ${plClass(position.unrealized_pl)}`}
      >
        {position.unrealized_pl == null
          ? '—'
          : `${position.unrealized_pl >= 0 ? '+' : ''}${formatCurrency(position.unrealized_pl)}`}
      </td>
      {/*
        Day column — spec §14.6 ships the structural column visible-but-`—`
        on desktop so layout doesn't shift when V0.7 adds backing data.
        Hidden on mobile.
      */}
      <td
        className="hidden lg:table-cell py-2 px-3 text-right text-slate-500 dark:text-slate-400"
        data-testid="dashboard-position-day"
      >
        —
      </td>
      <td className="py-2 px-3 text-center">
        <StatusPill status={position.wheel_status} />
      </td>
      <td className="py-2 px-3 text-right">
        <NextActionCell position={position} />
      </td>
    </tr>
  );
}

export default function DashboardPositionsCard({ positions, loading }) {
  if (loading) {
    return (
      <Card title="Positions" dataTestid="dashboard-positions-card">
        <div className="space-y-2" aria-busy="true">
          {[0, 1, 2].map((i) => (
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
      title="Positions"
      dataTestid="dashboard-positions-card"
      footer={
        <Link
          href="/journal"
          className="text-blue-600 dark:text-blue-400 hover:underline"
        >
          → Open Journal
        </Link>
      }
    >
      {positions?.length ? (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-slate-500 dark:text-slate-400 uppercase">
                <th className="py-2 px-3 text-left">Ticker</th>
                <th className="py-2 px-3 text-right">Shares</th>
                <th className="py-2 px-3 text-right">Cost basis</th>
                <th className="py-2 px-3 text-right">Current</th>
                <th className="py-2 px-3 text-right">%P/L</th>
                <th className="hidden lg:table-cell py-2 px-3 text-right">P/L</th>
                <th className="hidden lg:table-cell py-2 px-3 text-right">Day</th>
                <th className="py-2 px-3 text-center">Status</th>
                <th className="py-2 px-3 text-right">Next action</th>
              </tr>
            </thead>
            <tbody>
              {positions.map((position) => (
                <PositionRow key={position.id} position={position} />
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <EmptyState
          title="No positions yet"
          description="Import from Schwab or add a position manually."
          primaryAction={{ label: 'Open Journal', href: '/journal' }}
        />
      )}
    </Card>
  );
}
