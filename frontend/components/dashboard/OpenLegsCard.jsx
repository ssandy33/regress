'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import Card from '../common/Card';
import EmptyState from '../common/EmptyState';
import { formatPercent } from '../../utils/formatters';

/**
 * OpenLegsCard — triage-grade table of every open short option leg, and the
 * per-leg §R6 rule monitor (issue #240).
 *
 * V1.0.4 upgrade (issue #240 / spec §2–§3):
 *   - ACTION column reads `leg.verdict` (rule-driven) instead of the old
 *     DTE/moneyness `suggested_action`. The label string is server-rendered
 *     into `leg.verdict_label` ("Review · 50%" / "Hold" / …) so the frontend
 *     does no threshold parsing. Emerald = opportunity (profit-take), amber =
 *     scheduled review, red = deadline/assignment, slate = Hold.
 *   - Each row is a `<button>` toggle (was a `<Link>` to /journal). Clicking
 *     expands an inline InspectPanel — the rule-evaluation audit table. The
 *     journal navigation relocated into the panel's "Open in Journal" CTA.
 *   - A leading chevron cell shows the expand state; Ticker shrank 2→1 cols
 *     to make room (spec §5.1 Q8).
 *   - The card seeds its expanded set from `initialExpandedLegId` (the
 *     `#leg-{id}` deep-link from a card CTA — spec §4.4 Q7).
 *
 * V0.5 columns (issue #150) — %CAPTURED, RISK, earnings ⚠ glyph — unchanged.
 *
 * Responsive (spec §2.5 / §5.1):
 *   - Desktop (lg+): all columns visible — 1/1/1/2/1/2/1/1/2 = 12.
 *   - Mobile (< lg): %CAPTURED and RISK hidden; ACTION rendered only when the
 *     verdict is non-`hold`.
 */

function dteBadgeClass(dte) {
  if (dte <= 7) return 'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300';
  if (dte <= 14) return 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300';
  return 'bg-slate-100 text-slate-600 dark:bg-slate-700 dark:text-slate-200';
}

const PILL_SHAPE = 'inline-block px-2 py-0.5 text-xs rounded-full';

/**
 * coverageBadge — the per-leg covered/naked pill (issue #246, spec §2).
 *
 * Pure render helper. `covered` → quiet emerald pill; `naked` → amber `⚠`
 * pill (the exact recipe `dteBadgeClass` uses at `dte <= 14`). Any other
 * value (`null`/undefined — a short put or a pre-#246 payload) renders
 * nothing. The badge is severity, not scan: it carries no `hidden lg:*` and
 * survives every breakpoint. Stays pure — the InspectPanel echo wraps the
 * call in its own testid span (it does not pass an id in).
 */
function coverageBadge(coverage) {
  if (coverage === 'covered') {
    return (
      <span
        data-testid="dashboard-leg-row-coverage"
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
        data-testid="dashboard-leg-row-coverage"
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

/**
 * pnlDollarsText — the signed dollar-P&L line (issue #246, spec §3.2 / §3.5).
 *
 * Uses a LOCAL signed-currency formatter — `Intl`-based `formatCurrency()`
 * cannot emit the explicit `+` prefix the spec requires on gains, and the
 * explicit sign is an accessibility requirement (sign is not conveyed by
 * color alone). Gain → emerald `+$22.84`; loss → red `-$12.10`; zero or
 * unavailable (`null`/undefined — degraded path) → slate `—`.
 */
function pnlDollarsText(pnl) {
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

// Verdict map (spec §2.3) — keyed by `leg.verdict`. The label string itself
// is server-rendered into `leg.verdict_label` (so a user-set 65% threshold
// shows "Review · 65%"); this map only carries the per-verdict color + glyph.
// Emerald = opportunity, amber = scheduled review, red = deadline/assignment.
const VERDICT_VISUALS = {
  hold: {
    className: 'text-slate-600 dark:text-slate-300',
    glyph: '',
  },
  profit_take_review: {
    className: 'text-emerald-700 dark:text-emerald-300 font-medium',
    glyph: '',
  },
  dte_review: {
    className: 'text-amber-700 dark:text-amber-300 font-medium',
    glyph: '',
  },
  expiration: {
    className: 'text-red-700 dark:text-red-300 font-medium',
    glyph: '',
  },
  assignment: {
    className: 'text-red-700 dark:text-red-300 font-medium',
    glyph: '⛔',
  },
};

function ActionCell({ leg }) {
  const verdict = leg.verdict || 'hold';
  const visuals = VERDICT_VISUALS[verdict] || VERDICT_VISUALS.hold;
  const label = leg.verdict_label || 'Hold';
  // Mobile: hide a `hold` verdict (parity with the old non-urgent rule);
  // any non-hold verdict stays visible on mobile.
  const visibilityClass = verdict === 'hold' ? 'hidden lg:inline' : 'inline';
  return (
    <span
      data-verdict={verdict}
      className={`${visibilityClass} ${visuals.className}`}
    >
      {visuals.glyph && (
        <span aria-hidden="true" className="mr-0.5">
          {visuals.glyph}
        </span>
      )}
      {label}
    </span>
  );
}

// Tri-state status dot + label for the inspect table's "Triggered?" cell.
const STATUS_DISPLAY = {
  triggered: { dot: '●', label: 'Yes' },
  not_yet: { dot: '○', label: 'Not yet' },
  no: { dot: '○', label: 'No' },
};

function RuleStatusCell({ leg, rule }) {
  const display = STATUS_DISPLAY[rule.status] || STATUS_DISPLAY.no;
  const fired = rule.status === 'triggered';
  // The governing fired row takes the verdict color; a lower-precedence fired
  // row is neutral slate; non-firing rows inherit the greyed row class.
  let cellClass = '';
  if (fired && rule.is_governing) {
    const visuals = VERDICT_VISUALS[leg.verdict] || VERDICT_VISUALS.hold;
    cellClass = `font-medium ${visuals.className}`;
  } else if (fired) {
    cellClass = 'font-medium text-slate-600 dark:text-slate-300';
  }
  return (
    <td
      data-testid={`dashboard-leg-inspect-status-${leg.id}-${rule.rule_id}`}
      className={`py-1.5 ${cellClass}`}
    >
      <span aria-hidden="true">{display.dot}</span> {display.label}
    </td>
  );
}

/**
 * InspectPanel — the expanded per-leg rule-evaluation audit (spec §3.3–§3.4).
 *
 * Renders as a full-width row inside the 12-col grid. Shows every §R6 rule —
 * fired and not-fired alike — so the table reads as a monitor, not an alert
 * list. The reasoning sentence and the CTAs sit below the table.
 */
function InspectPanel({ leg }) {
  const optionLetter = leg.type === 'put' ? 'P' : 'C';
  const verdict = leg.verdict || 'hold';
  // A "closing" verdict gets a "Buy to close" CTA; a quiet/review leg does not.
  const showCloseCta =
    verdict === 'profit_take_review' ||
    verdict === 'expiration' ||
    verdict === 'assignment';
  const positionHref = `/journal?position=${encodeURIComponent(leg.position_id)}`;
  return (
    <div
      id={`dashboard-leg-inspect-${leg.id}`}
      data-testid={`dashboard-leg-inspect-${leg.id}`}
      className="col-span-12 bg-slate-50 dark:bg-slate-900/40 border border-slate-200 dark:border-slate-700 rounded-lg mt-1 mb-2 p-4"
    >
      <div className="text-sm font-medium text-slate-700 dark:text-slate-200 mb-1">
        {leg.ticker} ${leg.strike} {optionLetter} · exp {leg.expiration} ·{' '}
        {leg.dte} DTE
      </div>
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400 mb-2">
        Rule evaluation — checked against your Management Triggers
      </div>
      <table
        data-testid={`dashboard-leg-inspect-table-${leg.id}`}
        className="w-full text-sm border-collapse"
      >
        <thead>
          <tr className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-slate-700">
            <th className="text-left font-medium py-1.5">Metric</th>
            <th className="text-left font-medium py-1.5">Value</th>
            <th className="text-left font-medium py-1.5">Your rule</th>
            <th className="text-left font-medium py-1.5">Triggered?</th>
          </tr>
        </thead>
        <tbody>
          {(leg.triggered_rules || []).map((rule) => {
            const fired = rule.status === 'triggered';
            const rowClass = fired
              ? 'border-b border-slate-100 dark:border-slate-800 last:border-b-0'
              : 'border-b border-slate-100 dark:border-slate-800 last:border-b-0 text-slate-400 dark:text-slate-500';
            return (
              <tr
                key={rule.rule_id}
                data-testid={`dashboard-leg-inspect-rule-${leg.id}-${rule.rule_id}`}
                className={rowClass}
              >
                <td className="py-1.5">{rule.metric_label}</td>
                <td className="py-1.5 tabular-nums">{rule.value_display}</td>
                <td className="py-1.5">{rule.rule_display}</td>
                <RuleStatusCell leg={leg} rule={rule} />
              </tr>
            );
          })}
        </tbody>
      </table>
      <p
        data-testid={`dashboard-leg-inspect-reasoning-${leg.id}`}
        className="text-sm text-slate-600 dark:text-slate-300 mt-3"
      >
        {leg.reasoning || 'No management rule has triggered for this leg yet.'}
      </p>
      <div className="flex items-center gap-3 mt-3">
        {showCloseCta && (
          <Link
            href={`${positionHref}&action=close-leg`}
            data-testid={`dashboard-leg-inspect-cta-close-${leg.id}`}
            className="inline-flex items-center px-3 py-1.5 rounded-lg border border-slate-300 dark:border-slate-600 text-sm font-medium text-slate-700 dark:text-slate-200 hover:bg-slate-100 dark:hover:bg-slate-700"
          >
            Buy to close
          </Link>
        )}
        <Link
          href={positionHref}
          data-testid={`dashboard-leg-inspect-cta-journal-${leg.id}`}
          className="text-sm font-medium text-blue-600 dark:text-blue-400 hover:underline"
        >
          Open in Journal
          <span aria-hidden="true"> →</span>
        </Link>
      </div>
    </div>
  );
}

function LegRow({ leg, isExpanded, onToggle, rowRef }) {
  return (
    <button
      type="button"
      ref={rowRef}
      onClick={() => onToggle(leg.id)}
      aria-expanded={isExpanded}
      aria-controls={`dashboard-leg-inspect-${leg.id}`}
      data-testid="dashboard-leg-row"
      data-toggle-testid="dashboard-leg-row-toggle"
      data-leg-id={leg.id}
      className="w-full text-left grid grid-cols-12 gap-2 items-center py-2 border-b border-slate-100 dark:border-slate-700 last:border-b-0 hover:bg-slate-50 dark:hover:bg-slate-700/50 px-2 -mx-2 rounded text-sm cursor-pointer focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500"
    >
      {/*
        Mobile (< lg): chevron(1) + ticker(1) + strike(2) + exp(3) + dte(2) +
        moneyness(3) = 12; %captured & risk hidden; action wraps full-width.
        Desktop (lg+): 1/1/1/2/1/2/1/1/2 = 12.
      */}
      <span
        data-testid="dashboard-leg-row-chevron"
        aria-hidden="true"
        className="col-span-1 text-slate-400"
      >
        {isExpanded ? '▾' : '▸'}
      </span>
      <span className="col-span-1 lg:col-span-1 font-semibold text-slate-900 dark:text-white">
        {leg.ticker}
      </span>
      {/*
        Strike cell — a flex row so the coverage badge (#246) sits inline,
        right of the strike. `tabular-nums` is moved to an inner span so it
        applies to the number only, not the badge. Grid-neutral: no
        `col-span` change. The badge carries no `hidden lg:*` — it survives
        mobile (severity, not scan); `flex-wrap` handles a narrow cell.
      */}
      <span className="col-span-2 lg:col-span-1 flex items-center gap-1.5 flex-wrap text-slate-700 dark:text-slate-200">
        <span className="tabular-nums">
          {leg.strike} {leg.type === 'put' ? 'P' : 'C'}
        </span>
        {coverageBadge(leg.coverage)}
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
      {/*
        % Capt cell — a two-line stack (#246): the % CAPT percentage on top
        (unchanged), the signed dollar P&L below it. Stays `hidden lg:block`
        so on mobile both lines collapse together (the dollar P&L is a scan
        number, safe to collapse — unlike the coverage badge).
      */}
      <span
        data-testid="dashboard-leg-row-captured"
        className="hidden lg:block lg:col-span-1 tabular-nums leading-tight"
      >
        <span className="block">{capturedText(leg.profit_target_status)}</span>
        {pnlDollarsText(leg.pnl_dollars)}
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
        <ActionCell leg={leg} />
      </span>
    </button>
  );
}

function HeaderRow() {
  return (
    <div className="grid grid-cols-12 gap-2 items-center px-2 -mx-2 pb-2 mb-1 text-xs font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-slate-700">
      <span className="col-span-1" aria-hidden="true" />
      <span className="col-span-1 lg:col-span-1">Ticker</span>
      <span className="col-span-2 lg:col-span-1">Strike</span>
      <span className="col-span-3 lg:col-span-2">Exp</span>
      <span className="col-span-2 lg:col-span-1">DTE</span>
      <span className="col-span-3 lg:col-span-2">Moneyness</span>
      <span className="hidden lg:block lg:col-span-1">% Capt / P&amp;L</span>
      <span className="hidden lg:block lg:col-span-1">Risk</span>
      <span className="hidden lg:block lg:col-span-2">Action</span>
    </div>
  );
}

export default function OpenLegsCard({ legs, loading, initialExpandedLegId }) {
  // A Set of expanded leg ids — multi-open (spec §3.2 Q2). Seeded with the
  // `#leg-{id}` deep-link target, if any, on mount (spec §4.4 Q7).
  const [expanded, setExpanded] = useState(() => {
    const seed = new Set();
    if (initialExpandedLegId) seed.add(initialExpandedLegId);
    return seed;
  });
  const [deepLinkRow, setDeepLinkRow] = useState(null);

  // Scroll the deep-linked row into view once it mounts, honoring
  // prefers-reduced-motion (mirrors issue-182 §12.3).
  useEffect(() => {
    if (!initialExpandedLegId || !deepLinkRow) return;
    const motionOK =
      typeof window !== 'undefined' &&
      window.matchMedia &&
      !window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    deepLinkRow.scrollIntoView({
      behavior: motionOK ? 'smooth' : 'auto',
      block: 'center',
    });
  }, [initialExpandedLegId, deepLinkRow]);

  function toggle(legId) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(legId)) {
        next.delete(legId);
      } else {
        next.add(legId);
      }
      return next;
    });
  }

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
          <div className="grid grid-cols-12 gap-x-2">
            {legs.map((leg) => {
              const isExpanded = expanded.has(leg.id);
              return (
                <div key={leg.id} className="col-span-12 grid grid-cols-12 gap-2">
                  <div className="col-span-12">
                    <LegRow
                      leg={leg}
                      isExpanded={isExpanded}
                      onToggle={toggle}
                      rowRef={
                        leg.id === initialExpandedLegId ? setDeepLinkRow : null
                      }
                    />
                  </div>
                  {isExpanded && <InspectPanel leg={leg} />}
                </div>
              );
            })}
          </div>
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
