/**
 * Trading Rules field catalog (issue #158).
 *
 * The single source of the per-field UI metadata for the Settings → Trading
 * Rules section: label, helper text, units suffix, the catalog default shown
 * as a placeholder, the Optional flag, and the validation kind. The five
 * groups, the field keys, the whole-percent convention, the Optional set, and
 * the catalog defaults all mirror the backend `RulesConfig` model
 * (`backend/app/services/rules_config.py`, #156) — keep them in sync.
 *
 * Helper text is sourced from PRD #209 §R2–R6 and the design spec §5–§8.
 * `assignment_risk_review` is an enum — the backend models it as
 * `Literal["High", "Medium", "Low"]` (no "Off"); the select offers exactly
 * those three values.
 *
 * Q6 — the two cost-basis fields are distinct rules (#156 `EntryRules`
 * docstring): `min_call_distance_pct` is a *premium-quality margin above
 * adjusted cost basis*; `min_call_distance_from_cost_basis_pct` is a *bare
 * at-or-above-cost-basis loss-avoidance floor*. Their labels and helper text
 * below reflect those definitions.
 *
 * `validate` kinds (checked against the backend Pydantic validators):
 *   - 'oi'         : >= 0 (open interest, integer)
 *   - 'spreadPct'  : > 0 (a spread cap of 0 rejects every strike)
 *   - 'pct0to100'  : 0 <= x <= 100
 *   - 'pctOpen100' : 0 < x <= 100 (cap that cannot be 0)
 *   - 'nonNeg'     : >= 0
 *   - 'capPos'     : > 0 (sizing cap)
 *   - 'lossPct'    : <= 0 (a loss threshold is negative)
 *   - 'posInt'     : >= 1 when set (Optional)
 *   - 'nonNegInt'  : >= 0 when set (Optional)
 *   - 'delta'      : range, 0 <= bound <= 1, min < max
 *   - 'dte'        : range, min >= 0, min < max
 */

export const ASSIGNMENT_RISK_OPTIONS = ['Low', 'Medium', 'High'];

/** Group order matches the backend `_GROUP_MODELS` document order. */
export const GROUP_ORDER = ['universe', 'entry', 'position', 'risk', 'management'];

export const GROUP_META = {
  universe: {
    title: 'Universe',
    description:
      'May I trade this underlying at all? Checked before any option chain is scanned.',
  },
  entry: {
    title: 'Entry',
    description:
      'What trade may I open? Checked when a new option trade is opened or previewed in the scanner.',
  },
  position: {
    title: 'Position',
    description:
      'How big, how many? Caps on the capital tied up in any one position.',
  },
  risk: {
    title: 'Risk',
    description:
      'When do I intervene? Thresholds that flag a position for a deliberate look.',
  },
  management: {
    title: 'Management triggers',
    description:
      'When do I act on an open leg? Thresholds that fire Next Actions on positions you already hold.',
  },
};

/**
 * Per-group ordered field lists. `kind: 'range'` fields carry `{min, max}`;
 * everything else is a scalar. `default` is the catalog default (placeholder
 * for required fields; the value Reset-to-defaults restores).
 */
export const FIELDS = {
  universe: [
    {
      key: 'min_open_interest',
      label: 'Min option open interest',
      suffix: 'contracts',
      default: 500,
      optional: false,
      validate: 'oi',
      step: '1',
      helper:
        'Below this, bid-ask spreads widen enough to erode the edge. The standard liquidity floor for retail premium sellers.',
    },
    {
      key: 'max_bid_ask_spread_pct',
      label: 'Max bid-ask spread',
      suffix: '%',
      default: 10,
      optional: false,
      validate: 'spreadPct',
      helper:
        'A wider spread means you give up too much on entry and exit. A cheap proxy for tradeable liquidity.',
    },
    {
      key: 'min_iv_rank',
      label: 'IV Rank floor',
      suffix: null,
      default: 30,
      optional: false,
      validate: 'pct0to100',
      helper:
        'Below IV Rank 30, options are historically cheap and selling premium has no statistical edge. 30 is the minimum gate; 50+ is preferred.',
    },
    {
      key: 'min_iv_percentile',
      label: 'IV Percentile floor',
      suffix: null,
      default: null,
      optional: true,
      validate: 'pct0to100',
      helper:
        'Complementary to IV Rank — more stable against outlier spikes. Leave blank to skip this check.',
    },
  ],
  entry: [
    {
      key: 'dte_range',
      kind: 'range',
      label: 'DTE range',
      suffix: 'days',
      default: { min: 21, max: 45 },
      minLabel: 'DTE minimum',
      maxLabel: 'DTE maximum',
      validate: 'dte',
      step: '1',
      helper:
        'The wheel sweet spot — far enough for meaningful theta decay, near enough to avoid locking capital for months. Below 21 days gamma risk dominates.',
    },
    {
      key: 'delta_range_csp',
      kind: 'range',
      label: 'Delta range (cash-secured puts)',
      suffix: null,
      default: { min: 0.2, max: 0.3 },
      minLabel: 'CSP delta minimum',
      maxLabel: 'CSP delta maximum',
      validate: 'delta',
      helper:
        'A probability-of-assignment proxy. 0.20–0.30 is roughly a 70–80% chance the put expires worthless — the mainstream CSP consensus.',
    },
    {
      key: 'delta_range_cc',
      kind: 'range',
      label: 'Delta range (covered calls)',
      suffix: null,
      default: { min: 0.2, max: 0.35 },
      minLabel: 'Covered-call delta minimum',
      maxLabel: 'Covered-call delta maximum',
      validate: 'delta',
      helper:
        'Slightly wider — a higher delta is fine when you want shares called away above cost basis. Tighten it when you want to keep the shares.',
    },
    {
      key: 'min_monthly_return_pct',
      label: 'Min monthly return',
      suffix: '%',
      default: 2,
      optional: false,
      validate: 'nonNeg',
      helper:
        "A premium-yield floor. A trade earning under 2%/month doesn't justify the capital lockup and assignment risk.",
    },
    {
      key: 'earnings_buffer_days',
      label: 'Earnings buffer',
      suffix: 'days',
      default: 7,
      optional: false,
      validate: 'nonNeg',
      step: '1',
      helper:
        "Don't open within this many days of earnings — earnings gaps blow straight through strikes.",
    },
    {
      key: 'min_call_distance_pct',
      label: 'Min call distance above cost basis (margin)',
      suffix: '%',
      default: 5,
      optional: false,
      validate: 'nonNeg',
      helper:
        'The premium-quality margin: a covered-call strike must sit at least this far above your adjusted cost basis to be recommended. Measured from cost basis, not spot.',
    },
    {
      key: 'min_call_distance_from_cost_basis_pct',
      label: 'Min call distance — hard cost-basis floor',
      suffix: '%',
      default: 0,
      optional: false,
      validate: 'nonNeg',
      helper:
        'The hard loss-avoidance floor: never sell a covered call below this margin over cost basis — it locks in a loss if assigned. 0 means "at or above cost basis."',
    },
  ],
  position: [
    {
      key: 'sizing_cap_dollars',
      label: 'Per-position sizing cap',
      suffix: '$',
      suffixLeading: true,
      default: 5000,
      optional: false,
      validate: 'capPos',
      helper:
        'An absolute-dollar ceiling on capital tied up in one position — caps worst-case single-name loss regardless of account size.',
    },
    {
      key: 'max_ticker_concentration_pct',
      label: 'Ticker concentration cap',
      suffix: '%',
      default: 25,
      optional: false,
      validate: 'pctOpen100',
      helper:
        'No single ticker exceeds this share of total notional — survives a single-name blow-up.',
    },
    {
      key: 'max_open_positions',
      label: 'Max open positions',
      suffix: null,
      default: null,
      optional: true,
      validate: 'posInt',
      step: '1',
      helper:
        'A breadth guardrail — beyond a manageable count, monitoring discipline degrades. Leave blank for no cap. Most wheel practitioners cite 8–10.',
    },
  ],
  risk: [
    {
      key: 'loss_review_threshold_pct',
      label: 'Loss-review threshold',
      suffix: '%',
      default: -15,
      optional: false,
      validate: 'lossPct',
      helper:
        'A position down this much unrealized warrants a deliberate look — is the thesis still intact? Enter a negative number.',
    },
    {
      key: 'hard_max_loss_pct',
      label: 'Hard max-loss / stop',
      suffix: '%',
      default: null,
      optional: true,
      validate: 'lossPct',
      helper:
        'Past this loss, the position is a capital trap — decide via the recovery plan rather than hoping. Leave blank for no hard stop.',
    },
    {
      key: 'max_consecutive_rolls',
      label: 'Max consecutive rolls',
      suffix: '×',
      default: null,
      optional: true,
      validate: 'nonNegInt',
      step: '1',
      helper:
        'Rolling more than 2–3 times on the same loser usually just delays an inevitable assignment. At the cap, the system forces a decision. Leave blank for no cap.',
    },
  ],
  management: [
    {
      key: 'profit_review_pct',
      label: 'Profit-take review',
      suffix: '%',
      default: 50,
      optional: false,
      validate: 'pctOpen100',
      helper:
        'Buy back a short option at this share of max profit — locks gains, frees capital, sheds tail risk. Research across 200K+ trades supports 50%.',
    },
    {
      key: 'dte_review_days',
      label: 'DTE review',
      suffix: 'days',
      default: 21,
      optional: false,
      validate: 'nonNeg',
      step: '1',
      helper:
        'At this DTE, decide roll vs close vs hold. Inside it, gamma risk accelerates and a small adverse move can wipe out weeks of theta.',
    },
    {
      key: 'expiration_warning_days',
      label: 'Expiration warning',
      suffix: 'days',
      default: 7,
      optional: false,
      validate: 'nonNeg',
      step: '1',
      helper:
        'Inside this many days to expiry, assignment mechanics dominate and the position needs attention.',
    },
    {
      key: 'assignment_risk_review',
      label: 'Assignment-risk review',
      suffix: null,
      default: 'High',
      optional: false,
      kind: 'enum',
      options: ASSIGNMENT_RISK_OPTIONS,
      helper:
        'The sensitivity for flagging ITM-near-expiry positions that need an explicit decision.',
    },
  ],
};
