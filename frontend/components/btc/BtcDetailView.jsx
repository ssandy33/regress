// Composition surface for the populated / no-rule-triggered BTC detail state.
//
// Renders: leg header → recommended-action block ("banner") → buy-to-close
// economics panel → rule-audit panel → persistent disclaimer footer.
//
// The screen is the per-leg analog of the recovery screen. All four
// sub-components are kept local here, mirroring how RecoveryPlanPage keeps
// PositionHeader / EmptyState local.
//
// Spec: frontend/design-specs/issue-244-btc-detail-screen.md §5–§9.

import Link from 'next/link';

// --- Verdict color tokens (spec §9 — no new tokens) ------------------------

const VERDICT_TONE = {
  hold: {
    pill: 'bg-slate-100 dark:bg-slate-700 text-slate-600 dark:text-slate-300 border-slate-200 dark:border-slate-600',
    block: 'border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800',
    accent: 'text-slate-700 dark:text-slate-200',
    dot: 'text-slate-500 dark:text-slate-400',
  },
  profit_take_review: {
    pill: 'bg-emerald-50 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-300 border-emerald-300 dark:border-emerald-700',
    block: 'border-emerald-300 dark:border-emerald-700 bg-emerald-50 dark:bg-emerald-900/20',
    accent: 'text-emerald-800 dark:text-emerald-200',
    dot: 'text-emerald-700 dark:text-emerald-300',
  },
  dte_review: {
    pill: 'bg-amber-50 dark:bg-amber-900/30 text-amber-700 dark:text-amber-300 border-amber-300 dark:border-amber-700',
    block: 'border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20',
    accent: 'text-amber-800 dark:text-amber-200',
    dot: 'text-amber-700 dark:text-amber-300',
  },
  expiration: {
    pill: 'bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-300 border-red-300 dark:border-red-700',
    block: 'border-red-300 dark:border-red-700 bg-red-50 dark:bg-red-900/20',
    accent: 'text-red-800 dark:text-red-200',
    dot: 'text-red-700 dark:text-red-300',
  },
  assignment: {
    pill: 'bg-red-50 dark:bg-red-900/30 text-red-700 dark:text-red-300 border-red-300 dark:border-red-700',
    block: 'border-red-300 dark:border-red-700 bg-red-50 dark:bg-red-900/20',
    accent: 'text-red-800 dark:text-red-200',
    dot: 'text-red-700 dark:text-red-300',
  },
};

// The pill phrase per verdict — names the governing rule, attributed to the
// user's ruleset (spec §5.1 / §7.5). `⛔` glyph only on the assignment verdict.
const VERDICT_PILL_TEXT = {
  hold: 'No management rule has triggered for this leg yet',
  profit_take_review: 'Your profit-take rule triggered',
  dte_review: 'Your DTE review window reached',
  expiration: 'Your expiration warning triggered',
  assignment: 'Your expiration warning triggered — this leg is in the money',
};

// Closing verdicts surface the `Buy to close` CTA; dte_review and hold do not.
const CLOSING_VERDICTS = new Set(['profit_take_review', 'expiration', 'assignment']);

function tone(verdict) {
  return VERDICT_TONE[verdict] || VERDICT_TONE.hold;
}

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

function formatPct(value) {
  if (value === null || value === undefined) return '—';
  return `${Math.round(value * 100)}%`;
}

// --- LegHeader -------------------------------------------------------------

function LegHeader({ leg, verdict }) {
  const t = tone(verdict);
  const pillText = VERDICT_PILL_TEXT[verdict] || VERDICT_PILL_TEXT.hold;
  return (
    <div data-testid="btc-detail-leg-header">
      <h1 className="text-xl font-semibold text-slate-900 dark:text-white">
        Buy-to-close review: {leg.ticker} ${leg.strike} {leg.option_type}
      </h1>
      <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
        <Link
          href={`/journal?position=${encodeURIComponent(leg.position_id)}`}
          className="text-blue-700 dark:text-blue-300 hover:underline"
        >
          {leg.position_label}
        </Link>
        {' · '}
        {leg.contracts} contract{leg.contracts === 1 ? '' : 's'} · exp{' '}
        {leg.expiration} · {leg.dte} DTE
      </p>
      <span
        data-testid="btc-detail-rule-pill"
        data-verdict={verdict}
        className={`inline-flex items-center gap-1 mt-2 px-2 py-0.5 rounded-full text-xs font-medium border ${t.pill}`}
      >
        {verdict === 'assignment' && (
          <span aria-hidden="true">⛔</span>
        )}
        {pillText}
      </span>
    </div>
  );
}

// --- RecommendedActionBlock ------------------------------------------------

function RecommendedActionBlock({ data }) {
  const { verdict, leg, economics, triggered_rules: rules = [] } = data;
  const t = tone(verdict);
  const isHold = verdict === 'hold';
  const showCloseCta = CLOSING_VERDICTS.has(verdict);

  // First sentence: the governing rule's server-authored reasoning. Never
  // re-author it — it is already advice-framed. Then append the BTC outcome.
  const governing = rules.find((r) => r.is_governing) || null;
  let reasoning;
  if (isHold) {
    reasoning =
      'No management rule has triggered for this leg yet. Buying to close ' +
      'is still available as a manual action, but none of your Management ' +
      'Triggers are calling for it right now.';
  } else {
    const head =
      governing?.reasoning ||
      'Your management rule triggered for this leg.';
    let tail;
    if (economics.pricing_source !== 'live') {
      tail =
        " Live option pricing isn't connected, so cost-to-close and P/L " +
        "can't be shown right now.";
    } else if (
      verdict === 'profit_take_review' &&
      economics.est_pl_if_closed !== null &&
      economics.est_pl_if_closed !== undefined
    ) {
      tail = ` Buying to close now banks an estimated ${formatSignedDollar(
        economics.est_pl_if_closed,
      )} gain on this leg.`;
    } else if (
      economics.cost_to_close !== null &&
      economics.cost_to_close !== undefined
    ) {
      tail = ` Closing now costs ${formatDollar(
        economics.cost_to_close,
      )} against the ${formatDollar(
        economics.credit_received,
      )} credit you received.`;
    } else {
      tail = '';
    }
    reasoning = `${head}${tail}`;
  }

  return (
    <div
      data-testid="btc-detail-recommended-action"
      data-verdict={verdict}
      className={`rounded-xl border p-4 ${t.block}`}
    >
      <p
        data-testid="btc-detail-recommended-reasoning"
        className="text-sm text-slate-700 dark:text-slate-200"
      >
        {reasoning}
      </p>
      <div className="mt-3 flex items-center gap-4">
        {showCloseCta && (
          <Link
            href={
              `/journal?position=${encodeURIComponent(leg.position_id)}` +
              `&leg=${encodeURIComponent(leg.id)}&action=close-leg`
            }
            data-testid="btc-detail-cta-close"
            className="inline-flex items-center px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700"
          >
            Buy to close
          </Link>
        )}
        <Link
          href={`/journal?position=${encodeURIComponent(leg.position_id)}`}
          data-testid="btc-detail-cta-journal"
          className="text-sm font-medium text-blue-700 dark:text-blue-300 hover:underline"
        >
          Open in Journal
          <span aria-hidden="true"> →</span>
        </Link>
      </div>
    </div>
  );
}

// --- BtcEconomicsPanel -----------------------------------------------------

function EconomicsTile({ testId, label, value, valueClass }) {
  return (
    <div data-testid={testId}>
      <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {label}
      </div>
      <div
        className={`text-2xl font-semibold tabular-nums mt-1 ${
          valueClass || 'text-slate-900 dark:text-white'
        }`}
      >
        {value}
      </div>
    </div>
  );
}

function BtcEconomicsPanel({ economics, analysis, verdict }) {
  const pricingLive = economics.pricing_source === 'live';
  const captured = economics.captured_pct;
  // The honest decision signal that replaces the misleading "% premium
  // captured" tile in the BTC detail context (issue #319). Comes from the
  // analysis decomposition, NOT captured_pct.
  const extrinsicPct = analysis?.extrinsic_pct_of_mid;
  const extrinsicPctClass = pricingLive
    ? 'text-slate-900 dark:text-white'
    : 'text-slate-400 dark:text-slate-500';
  const estPl = economics.est_pl_if_closed;
  let estPlClass = 'text-slate-400 dark:text-slate-500';
  if (estPl !== null && estPl !== undefined) {
    estPlClass =
      estPl < 0
        ? 'text-red-700 dark:text-red-300'
        : 'text-emerald-700 dark:text-emerald-300';
  }
  const stubClass = pricingLive
    ? 'text-slate-900 dark:text-white'
    : 'text-slate-400 dark:text-slate-500';

  let caption;
  if (pricingLive) {
    const asOf = economics.pricing_as_of
      ? new Date(economics.pricing_as_of).toLocaleString()
      : 'now';
    caption = `Option mid as of ${asOf} · est. P/L excludes commissions.`;
  } else {
    caption =
      "Live option pricing isn't connected — cost-to-close and P/L can't " +
      'be shown. The rule audit below still applies.';
  }

  return (
    <div
      data-testid="btc-detail-economics"
      className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800"
    >
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between">
        <h3 className="text-base font-semibold text-slate-900 dark:text-white">
          Buy-to-close economics
        </h3>
        {!pricingLive && (
          <span
            data-testid="btc-detail-economics-stub-badge"
            className="px-2 py-0.5 rounded-full text-[11px] font-medium bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400"
          >
            Pricing unavailable
          </span>
        )}
      </div>
      <div className="p-4">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <EconomicsTile
            testId="btc-detail-economics-tile-cost-to-close"
            label="Cost to close"
            value={formatDollar(economics.cost_to_close)}
            valueClass={stubClass}
          />
          <EconomicsTile
            testId="btc-detail-economics-tile-credit"
            label="Credit received"
            value={formatDollar(economics.credit_received)}
          />
          <EconomicsTile
            testId="btc-detail-economics-tile-extrinsic-pct"
            label="Extrinsic % of mid"
            value={formatPct(extrinsicPct)}
            valueClass={extrinsicPctClass}
          />
          <EconomicsTile
            testId="btc-detail-economics-tile-est-pl"
            label="Est. P/L if closed"
            value={formatSignedDollar(economics.est_pl_if_closed)}
            valueClass={estPlClass}
          />
        </div>
        {captured !== null && captured !== undefined && (
          <p
            data-testid="btc-detail-economics-captured-raw-note"
            className="text-xs text-slate-400 dark:text-slate-500 mt-3"
          >
            Premium captured (raw):{' '}
            <span className="tabular-nums">{formatPct(captured)}</span> —
            distorted by intrinsic value on deep-ITM legs; see BTC Analysis
            below.
          </p>
        )}
        <p
          data-testid="btc-detail-economics-caption"
          className="text-xs text-slate-500 dark:text-slate-400 mt-1"
        >
          {caption}
        </p>
      </div>
    </div>
  );
}

// --- RuleAuditPanel --------------------------------------------------------

const STATUS_DISPLAY = {
  triggered: { dot: '●', label: 'Yes' },
  not_yet: { dot: '○', label: 'Not yet' },
  no: { dot: '○', label: 'No' },
};

function RuleAuditPanel({ rules, verdict }) {
  const t = tone(verdict);
  const governing = rules.find((r) => r.is_governing) || null;
  const reasoning =
    governing?.reasoning || 'No management rule has triggered for this leg yet.';

  return (
    <div
      data-testid="btc-detail-rule-audit"
      className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800"
    >
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700">
        <h3 className="text-base font-semibold text-slate-900 dark:text-white">
          Rule audit — checked against your Management Triggers
        </h3>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
          Every management rule you&apos;ve configured, evaluated for this leg.
        </p>
      </div>
      <div className="p-4">
        <table
          data-testid="btc-detail-rule-audit-table"
          className="w-full text-sm"
        >
          <thead>
            <tr className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-slate-700">
              <th className="text-left font-medium pb-2">Metric</th>
              <th className="text-left font-medium pb-2">Value</th>
              <th className="text-left font-medium pb-2">Your rule</th>
              <th className="text-left font-medium pb-2">Triggered?</th>
            </tr>
          </thead>
          <tbody>
            {rules.map((rule) => {
              const display = STATUS_DISPLAY[rule.status] || STATUS_DISPLAY.no;
              const fired = rule.status === 'triggered';
              const rowClass = fired
                ? 'text-slate-700 dark:text-slate-200 border-b border-slate-100 dark:border-slate-700/50 last:border-b-0'
                : 'text-slate-400 dark:text-slate-500 border-b border-slate-100 dark:border-slate-700/50 last:border-b-0';
              // The governing fired row takes the verdict color; a
              // lower-precedence fired row is neutral slate.
              let statusClass = '';
              if (fired && rule.is_governing) {
                statusClass = `font-medium ${t.dot}`;
              } else if (fired) {
                statusClass = 'text-slate-500 dark:text-slate-400';
              }
              return (
                <tr
                  key={rule.rule_id}
                  data-testid={`btc-detail-rule-audit-row-${rule.rule_id}`}
                  className={rowClass}
                >
                  <td className={`py-2 ${fired && rule.is_governing ? 'font-medium' : ''}`}>
                    {rule.metric_label}
                  </td>
                  <td className="py-2 tabular-nums">{rule.value_display}</td>
                  <td className="py-2">{rule.rule_display}</td>
                  <td
                    data-testid={`btc-detail-rule-audit-status-${rule.rule_id}`}
                    className={`py-2 ${statusClass}`}
                  >
                    <span aria-hidden="true">{display.dot}</span> {display.label}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p
          data-testid="btc-detail-rule-audit-reasoning"
          className="text-sm text-slate-600 dark:text-slate-300 mt-3"
        >
          {reasoning}
        </p>
      </div>
    </div>
  );
}

// --- BtcAnalysisPanel (issue #319) -----------------------------------------

// Section 1 figure (decomposition trio) — smaller than EconomicsTile, 3-up.
function AnalysisFigure({ testId, label, value, valueClass, note }) {
  return (
    <div data-testid={testId}>
      <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
        {label}
      </div>
      <div
        className={`text-2xl font-semibold tabular-nums mt-1 ${
          valueClass || 'text-slate-900 dark:text-white'
        }`}
      >
        {value}
      </div>
      {note && (
        <div className="text-[11px] text-slate-400 dark:text-slate-500 mt-0.5">
          {note}
        </div>
      )}
    </div>
  );
}

const ANALYSIS_HEADING = 'BTC Analysis — let assign vs. buy to close';

function BtcAnalysisPanel({ analysis }) {
  if (!analysis) return null;

  // Three render states: full-degrade (available === false), greek-null
  // (available, but no option mid → intrinsic-only), and populated.
  const degraded = analysis.available === false;
  const greekNull = !degraded && analysis.option_mid === null;
  const populated = !degraded && !greekNull;

  return (
    <div
      data-testid="btc-analysis"
      data-degrade={greekNull ? 'greek-null' : undefined}
      className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800"
    >
      <div className="px-4 py-3 border-b border-slate-200 dark:border-slate-700 flex items-center justify-between">
        <h3 className="text-base font-semibold text-slate-900 dark:text-white">
          {ANALYSIS_HEADING}
        </h3>
        {(degraded || greekNull) && (
          <span
            data-testid="btc-analysis-degraded-badge"
            className="px-2 py-0.5 rounded-full text-[11px] font-medium bg-slate-100 dark:bg-slate-700 text-slate-500 dark:text-slate-400"
          >
            {greekNull ? 'Option mid missing' : 'Pricing unavailable'}
          </span>
        )}
      </div>

      <div className="p-4 space-y-5">
        {/* Section 1 — decomposition trio */}
        <div className={`grid grid-cols-3 gap-4 ${degraded ? 'opacity-60' : ''}`}>
          <AnalysisFigure
            testId="btc-analysis-intrinsic"
            label="Intrinsic value"
            value={formatDollar(analysis.intrinsic)}
            valueClass={
              analysis.intrinsic === null || analysis.intrinsic === undefined
                ? 'text-slate-400 dark:text-slate-500'
                : undefined
            }
          />
          <AnalysisFigure
            testId="btc-analysis-extrinsic"
            label="Extrinsic (time) value"
            value={formatDollar(analysis.extrinsic)}
            valueClass={
              analysis.extrinsic === null || analysis.extrinsic === undefined
                ? 'text-slate-400 dark:text-slate-500'
                : undefined
            }
            note={greekNull ? 'Needs option mid' : undefined}
          />
          <AnalysisFigure
            testId="btc-analysis-extrinsic-pct"
            label="Extrinsic % of mid"
            value={formatPct(analysis.extrinsic_pct_of_mid)}
            valueClass={
              analysis.extrinsic_pct_of_mid === null ||
              analysis.extrinsic_pct_of_mid === undefined
                ? 'text-slate-400 dark:text-slate-500'
                : undefined
            }
          />
        </div>

        {/* Sections 2 + 3 — only when fully populated */}
        {populated ? (
          <>
            <div className="border-t border-slate-100 dark:border-slate-700/50 pt-4">
              <p
                data-testid="btc-analysis-breakeven"
                className="text-sm text-slate-800 dark:text-slate-100"
              >
                <span className="font-semibold">
                  BTC breakeven at expiration:{' '}
                  <span className="tabular-nums">
                    {formatDollar(analysis.btc_breakeven)}
                  </span>
                </span>
                <span className="text-slate-500 dark:text-slate-400">
                  {' · '}Underlying{' '}
                  <span className="tabular-nums">
                    {formatDollar(analysis.underlying)}
                  </span>{' '}
                </span>
                <span
                  data-testid="btc-analysis-breakeven-delta"
                  className={`tabular-nums font-medium ${
                    analysis.breakeven_delta < 0
                      ? 'text-red-700 dark:text-red-300'
                      : 'text-emerald-700 dark:text-emerald-300'
                  }`}
                >
                  ({formatSignedDollar(analysis.breakeven_delta)}{' '}
                  {analysis.breakeven_delta < 0 ? 'below' : 'above'} breakeven)
                </span>
              </p>
              <p
                data-testid="btc-analysis-guidance"
                className="text-sm text-slate-600 dark:text-slate-300 mt-2 max-w-prose"
              >
                The stock must rise above your BTC breakeven (
                <span className="font-medium tabular-nums">
                  {formatDollar(analysis.btc_breakeven)}
                </span>
                ) by expiration for buying to close to beat letting the shares
                get called away. That&apos;s{' '}
                <span className="font-medium tabular-nums">
                  {formatDollar(analysis.extrinsic)}
                </span>{' '}
                of remaining time value the stock has to clear. Below breakeven,
                letting it assign keeps more.
              </p>
            </div>

            <div className="border-t border-slate-100 dark:border-slate-700/50 pt-4">
              <table
                data-testid="btc-analysis-scenario-table"
                className="w-full text-sm"
              >
                <thead>
                  <tr className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400 border-b border-slate-200 dark:border-slate-700">
                    <th scope="col" className="text-left font-medium pb-2">
                      Underlying @ exp
                    </th>
                    <th scope="col" className="text-left font-medium pb-2">
                      Let assign
                    </th>
                    <th scope="col" className="text-left font-medium pb-2">
                      BTC + hold
                    </th>
                    <th scope="col" className="text-left font-medium pb-2">
                      Δ (BTC − assign)
                    </th>
                    <th scope="col" className="text-left font-medium pb-2">
                      Winner
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {analysis.scenarios.map((s, i) => {
                    const btcWins = s.winner === 'btc';
                    const deltaClass = btcWins
                      ? 'text-emerald-700 dark:text-emerald-300 font-medium'
                      : 'text-slate-700 dark:text-slate-200';
                    return (
                      <tr
                        key={s.label}
                        data-testid={`btc-analysis-scenario-row-${i}`}
                        className="text-slate-700 dark:text-slate-200 border-b border-slate-100 dark:border-slate-700/50 last:border-b-0"
                      >
                        <td className="py-2 tabular-nums">
                          {formatDollar(s.underlying)}{' '}
                          <span className="text-slate-400">({s.label})</span>
                        </td>
                        <td className="py-2 tabular-nums">
                          {formatDollar(s.let_assign)}
                        </td>
                        <td className="py-2 tabular-nums">
                          {formatDollar(s.btc_and_hold)}
                        </td>
                        <td
                          data-testid={`btc-analysis-scenario-delta-${i}`}
                          className={`py-2 tabular-nums ${deltaClass}`}
                        >
                          {formatSignedDollar(s.delta)}
                        </td>
                        <td
                          className={`py-2 ${
                            btcWins ? 'text-emerald-700 dark:text-emerald-300' : ''
                          }`}
                        >
                          {btcWins ? 'BTC wins' : 'Assign wins'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="text-xs text-slate-400 dark:text-slate-500 mt-3">
                Net dollars per scenario, pre-commission. Δ &gt; 0 means buying
                to close beats letting assign at that price.
              </p>
            </div>
          </>
        ) : (
          <p className="text-sm text-slate-500 dark:text-slate-400 border-t border-slate-100 dark:border-slate-700/50 pt-4">
            {greekNull
              ? 'The option chain returned no mark for this strike, so breakeven and the assign-vs-BTC scenarios can’t be computed. Intrinsic value is shown from the live underlying.'
              : 'Decomposition, breakeven, and scenarios need a live option mark and underlying price. They’ll appear once pricing reconnects.'}
          </p>
        )}
      </div>
    </div>
  );
}

// --- BtcDetailView ---------------------------------------------------------

export default function BtcDetailView({ data }) {
  if (!data || !data.leg) return null;
  const {
    leg,
    verdict,
    economics,
    analysis,
    triggered_rules: rules = [],
    disclaimer,
  } = data;

  return (
    <div className="space-y-4">
      <LegHeader leg={leg} verdict={verdict} />
      <RecommendedActionBlock data={data} />
      <BtcEconomicsPanel
        economics={economics}
        analysis={analysis}
        verdict={verdict}
      />
      <BtcAnalysisPanel analysis={analysis} />
      <RuleAuditPanel rules={rules} verdict={verdict} />

      <footer
        data-testid="btc-detail-disclaimer"
        className="mt-4 p-4 rounded-lg bg-slate-100 dark:bg-slate-800/40 border border-slate-200 dark:border-slate-700"
        aria-label="Buy-to-close disclaimer"
      >
        <p className="text-xs text-slate-500 dark:text-slate-400 max-w-prose mx-auto text-center">
          {disclaimer}
        </p>
      </footer>
    </div>
  );
}
