// Phase 1.5 mock — placeholder for spec implementation. Replace during Phase 3.
//
// Stories for ScannerRejectedStrikes (issue #190, Affordance 4).
// Demonstrates: single-rule rejection, multi-rule rejection, many strikes
// rejected (collapsed disclosure surface), and unknown-code fallback.

import ScannerRejectedStrikes, { REJECTION_COPY } from './ScannerRejectedStrikes';

const meta = {
  title: 'Options/ScannerRejectedStrikes',
  component: ScannerRejectedStrikes,
  parameters: {
    layout: 'padded',
    docs: {
      description: {
        component:
          'Humanized rejected-strikes disclosure. Bulleted plain-English ' +
          'sentences in neutral slate color (not red — these are explanations, ' +
          'not errors). Unknown rejection codes degrade to the raw string so ' +
          'the user is never blind to a real signal.',
      },
    },
  },
};

export default meta;

const single = [
  {
    strike: 12.50,
    expiration: '2026-06-18',
    rejection_reasons: ['fails_10pct_rule'],
    human_reasons: [REJECTION_COPY.fails_10pct_rule],
  },
];

const multi = [
  {
    strike: 16.00,
    expiration: '2026-06-18',
    rejection_reasons: ['delta_out_of_range', 'low_open_interest', 'zero_bid'],
    human_reasons: [
      REJECTION_COPY.delta_out_of_range,
      REJECTION_COPY.low_open_interest,
      REJECTION_COPY.zero_bid,
    ],
  },
];

// Mix one strike with reasons expanded out of 50 total.
const many = (() => {
  const out = [];
  const expirations = ['2026-06-18', '2026-07-16', '2026-08-20'];
  const codes = [
    ['fails_10pct_rule'],
    ['delta_out_of_range'],
    ['low_open_interest'],
    ['zero_bid'],
    ['return_below_target'],
    ['delta_out_of_range', 'low_open_interest'],
  ];
  for (let i = 0; i < 50; i++) {
    const r = codes[i % codes.length];
    out.push({
      strike: 10 + i * 0.5,
      expiration: expirations[i % expirations.length],
      rejection_reasons: r,
      human_reasons: r.map((c) => REJECTION_COPY[c]),
    });
  }
  return out;
})();

const unknown = [
  {
    strike: 14.50,
    expiration: '2026-06-18',
    rejection_reasons: ['some_future_rule_code_we_have_not_mapped_yet'],
    // No human_reasons → component falls back to humanize(code) which returns
    // the raw string when the code is not in REJECTION_COPY.
  },
];

export const SingleRuleRejection = {
  name: 'Single-rule rejection — fails_10pct_rule',
  args: {
    rejected: single,
    defaultOpen: true,
  },
};

export const MultiRuleRejection = {
  name: 'Multi-rule rejection — delta + OI + zero bid',
  args: {
    rejected: multi,
    defaultOpen: true,
  },
};

export const ManyStrikesCollapsed = {
  name: 'Many strikes rejected (50) — disclosure',
  args: {
    rejected: many,
    defaultOpen: false,
  },
};

export const ManyStrikesExpanded = {
  name: 'Many strikes rejected (50) — expanded',
  args: {
    rejected: many,
    defaultOpen: true,
    visibleCount: 5,
  },
};

export const UnknownReasonCode = {
  name: 'Unknown reason code — fallback rendering',
  args: {
    rejected: unknown,
    defaultOpen: true,
  },
};
