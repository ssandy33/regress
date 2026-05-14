// Stories for ScannerRejectedStrikes (issue #190, Affordance 4).
//
// Demonstrates: single-rule rejection, multi-rule rejection, many strikes
// rejected (collapsed disclosure surface), and unknown-code fallback. The
// component receives realistic `human_reasons` strings — in production these
// are populated server-side by `backend/app/services/rejection_messages.py`.

import ScannerRejectedStrikes from './ScannerRejectedStrikes';

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
    strike: 12.5,
    expiration: '2026-06-18',
    rejection_reasons: ['fails_10pct_rule: strike -5.4% above basis, requires 10.0%'],
    human_reasons: [
      'Strike sits -5.4% above your $13.21 basis, but the 10.0% rule requires at least that much room.',
    ],
  },
];

const multi = [
  {
    strike: 16.0,
    expiration: '2026-06-18',
    rejection_reasons: [
      'delta_out_of_range: |0.42| not in [0.15, 0.35]',
      'low_open_interest: 12 < 50',
      'zero_bid',
    ],
    human_reasons: [
      'Delta +0.42 is outside your 0.15–0.35 range — too close to the money, higher chance of assignment than you have set as acceptable.',
      'Only 12 contracts open — too thin to trade comfortably (the scanner requires at least 50).',
      'No buyer is showing a bid right now, so there is no real market to sell into.',
    ],
  },
];

// 50 strikes with realistic backend-emitted humanized strings.
const many = (() => {
  const samples = [
    {
      raw: 'fails_10pct_rule: strike -8.1% above basis, requires 10.0%',
      human:
        'Strike sits -8.1% above your $13.21 basis, but the 10.0% rule requires at least that much room.',
    },
    {
      raw: 'delta_out_of_range: |0.42| not in [0.15, 0.35]',
      human:
        'Delta +0.42 is outside your 0.15–0.35 range — too close to the money, higher chance of assignment than you have set as acceptable.',
    },
    {
      raw: 'low_open_interest: 12 < 50',
      human:
        'Only 12 contracts open — too thin to trade comfortably (the scanner requires at least 50).',
    },
    {
      raw: 'zero_bid',
      human: 'No buyer is showing a bid right now, so there is no real market to sell into.',
    },
    {
      raw: 'return_below_target: 0.42% < 1.0%',
      human: 'Premium is only 0.42% of capital — below your 1.0% target return.',
    },
  ];
  const expirations = ['2026-06-18', '2026-07-16', '2026-08-20'];
  const out = [];
  for (let i = 0; i < 50; i++) {
    const sample = samples[i % samples.length];
    out.push({
      strike: 10 + i * 0.5,
      expiration: expirations[i % expirations.length],
      rejection_reasons: [sample.raw],
      human_reasons: [sample.human],
    });
  }
  return out;
})();

const unknown = [
  {
    strike: 14.5,
    expiration: '2026-06-18',
    // No human_reasons populated → component falls back to mapping the raw
    // prefix client-side. The defensive CLIENT_COPY_FALLBACK does not include
    // this future code, so the raw string passes through unchanged.
    rejection_reasons: ['some_future_rule_code_we_have_not_mapped_yet: extra params'],
  },
];

export const SingleRuleRejection = {
  name: 'Single-rule rejection — fails_10pct_rule',
  args: { rejected: single, defaultOpen: true },
};

export const MultiRuleRejection = {
  name: 'Multi-rule rejection — delta + OI + zero bid',
  args: { rejected: multi, defaultOpen: true },
};

export const ManyStrikesCollapsed = {
  name: 'Many strikes rejected (50) — disclosure',
  args: { rejected: many, defaultOpen: false },
};

export const ManyStrikesExpanded = {
  name: 'Many strikes rejected (50) — expanded',
  args: { rejected: many, defaultOpen: true, visibleCount: 5 },
};

export const UnknownReasonCode = {
  name: 'Unknown reason code — fallback rendering',
  args: { rejected: unknown, defaultOpen: true },
};
