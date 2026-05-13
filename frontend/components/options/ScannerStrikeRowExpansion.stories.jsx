// Phase 1.5 mock — placeholder for spec implementation. Replace during Phase 3.
//
// Stories for ScannerStrikeRowExpansion (issue #190, Affordance 3).
// Mirrors the F-position numbers from the spec: 100 shares, $13.21 basis,
// $0.18 premium, 36 DTE.

import { useState } from 'react';
import ScannerStrikeRowExpansion from './ScannerStrikeRowExpansion';

const meta = {
  title: 'Options/ScannerStrikeRowExpansion',
  component: ScannerStrikeRowExpansion,
  parameters: {
    layout: 'padded',
    docs: {
      description: {
        component:
          'Per-row "What this trade commits you to" sub-section. Appended below ' +
          'the existing Greeks / Metrics / Rule-Compliance panel — not a replacement. ' +
          'All math derives from fields the scanner already returns.',
      },
    },
  },
};

export default meta;

const F_CC_15 = {
  strategy: 'cc',
  strike: 15.0,
  expiration: '2026-06-18',
  dte: 36,
  premium_per_contract: 18.0, // $0.18 mid × 100
  breakeven: 13.03, // 13.21 basis - 0.18 premium
  fifty_pct_profit_target: 9.0,
  cost_basis_per_share: 13.21,
  contracts: 1,
  shares_held: 100,
};

const F_CSP_13 = {
  strategy: 'csp',
  strike: 13.0,
  expiration: '2026-06-18',
  dte: 36,
  premium_per_contract: 32.0, // $0.32 × 100
  breakeven: 12.68, // 13.00 - 0.32
  fifty_pct_profit_target: 16.0,
  contracts: 1,
};

// Wraps the expansion in a faux table row so it renders in context.
function TableShell({ children, collapsed = false }) {
  const [open, setOpen] = useState(!collapsed);
  return (
    <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 dark:bg-slate-900 border-b border-slate-200 dark:border-slate-700">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-medium text-slate-500 dark:text-slate-400">Strike</th>
            <th className="px-3 py-2 text-right text-xs font-medium text-slate-500 dark:text-slate-400">Delta</th>
            <th className="px-3 py-2 text-right text-xs font-medium text-slate-500 dark:text-slate-400">Premium</th>
            <th className="px-3 py-2 text-right text-xs font-medium text-slate-500 dark:text-slate-400">Ann.%</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-700">
          <tr
            className="hover:bg-slate-50 dark:hover:bg-slate-700/50 cursor-pointer"
            onClick={() => setOpen((v) => !v)}
          >
            <td className="px-3 py-2 font-medium text-green-700 dark:text-green-400">$15.00</td>
            <td className="px-3 py-2 text-right text-slate-700 dark:text-slate-300">0.28</td>
            <td className="px-3 py-2 text-right font-medium text-slate-900 dark:text-white">$0.18</td>
            <td className="px-3 py-2 text-right text-blue-600 dark:text-blue-400">14.0%</td>
          </tr>
          {open && (
            <tr>
              <td colSpan={4} className="px-6 py-4 bg-slate-50 dark:bg-slate-900/50">
                {children}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

export const Collapsed = {
  render: () => (
    <TableShell collapsed>
      <ScannerStrikeRowExpansion {...F_CC_15} />
    </TableShell>
  ),
};

export const ExpandedCoveredCall = {
  name: 'Expanded — Covered Call $15 strike',
  render: () => (
    <TableShell>
      <ScannerStrikeRowExpansion {...F_CC_15} />
    </TableShell>
  ),
};

export const ExpandedCashSecuredPut = {
  name: 'Expanded — Cash-Secured Put $13 strike',
  render: () => (
    <TableShell>
      <ScannerStrikeRowExpansion {...F_CSP_13} />
    </TableShell>
  ),
};

export const ExpandedWithEarningsFlag = {
  name: 'Expanded — earnings-in-window flagged',
  render: () => (
    <TableShell>
      <ScannerStrikeRowExpansion {...F_CC_15} earnings_in_window />
    </TableShell>
  ),
};
