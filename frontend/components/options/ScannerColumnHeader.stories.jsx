// Phase 1.5 mock — placeholder for spec implementation. Replace during Phase 3.
//
// Stories for ScannerColumnHeader (issue #190, Affordance 2).
// Wraps the header in a real <table> shell so the tooltip positioning and
// sort affordance are inspectable in the same context they ship in.

import ScannerColumnHeader from './ScannerColumnHeader';

const TOOLTIPS = {
  delta: {
    definition:
      'The option price\'s sensitivity to a $1 move in the underlying. Roughly the market-implied probability the option ends in the money.',
    range: 'For wheel strategies: 0.20 to 0.35. Lower = safer, less premium.',
    whyItMatters:
      'Higher delta means more premium but a higher chance of assignment. Stay in your comfort zone.',
  },
  open_interest: {
    definition:
      'The number of outstanding contracts at this strike that have not been closed or exercised.',
    range: 'Look for 500+ contracts. 100+ is acceptable on less liquid names.',
    whyItMatters:
      'Higher open interest = tighter bid/ask spreads and easier exits. Thin contracts can cost you 5-10% on slippage.',
  },
  annualized_return_pct: {
    definition:
      'The return on capital, scaled to a full year. Lets you compare 7-day premiums against 45-day premiums on equal footing.',
    range: 'Target 20%+ annualized for wheel candidates. Below 15% is rarely worth the assignment risk.',
    whyItMatters:
      'A $1 premium on a 7-DTE contract beats a $1.50 premium on 45-DTE every time, once you scale it.',
  },
};

function HeaderHarness({ field, label, tooltipKey, active = false, forceTooltipOpen = false }) {
  // Render inside a real table so absolutely-positioned tooltip looks right.
  return (
    <div className="bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl overflow-visible">
      <table className="w-full text-sm">
        <thead className="bg-slate-50 dark:bg-slate-900 border-b border-slate-200 dark:border-slate-700">
          <tr>
            <th className="px-3 py-2 text-left text-xs font-medium text-slate-500 dark:text-slate-400">
              Strike
            </th>
            <ScannerColumnHeader
              field={field}
              label={label}
              tooltip={tooltipKey ? TOOLTIPS[tooltipKey] : null}
              active={active}
              sortDir="desc"
              onSort={() => {}}
              forceTooltipOpen={forceTooltipOpen}
            />
            <th className="px-3 py-2 text-right text-xs font-medium text-slate-500 dark:text-slate-400">
              Premium
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 dark:divide-slate-700">
          <tr>
            <td className="px-3 py-2 text-slate-700 dark:text-slate-300">$15.00</td>
            <td className="px-3 py-2 text-right text-slate-700 dark:text-slate-300">0.28</td>
            <td className="px-3 py-2 text-right font-medium text-slate-900 dark:text-white">$0.42</td>
          </tr>
          <tr>
            <td className="px-3 py-2 text-slate-700 dark:text-slate-300">$14.50</td>
            <td className="px-3 py-2 text-right text-slate-700 dark:text-slate-300">0.31</td>
            <td className="px-3 py-2 text-right font-medium text-slate-900 dark:text-white">$0.55</td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

const meta = {
  title: 'Options/ScannerColumnHeader',
  component: ScannerColumnHeader,
  parameters: {
    layout: 'padded',
    docs: {
      description: {
        component:
          'Header cell with a dedicated info icon for tooltip content (definition / ' +
          'good range / why it matters). The `ⓘ` is separate from the sort click ' +
          'target — they coexist visually and via keyboard.',
      },
    },
  },
};

export default meta;

export const DefaultNoTooltipOpen = {
  name: 'Default — No Tooltip Open',
  render: () => (
    <HeaderHarness field="delta" label="Delta" tooltipKey="delta" />
  ),
};

export const TooltipOpenDelta = {
  name: 'Tooltip Open — Delta',
  render: () => (
    <HeaderHarness field="delta" label="Delta" tooltipKey="delta" forceTooltipOpen />
  ),
};

export const TooltipOpenOI = {
  name: 'Tooltip Open — OI',
  render: () => (
    <HeaderHarness
      field="open_interest"
      label="OI"
      tooltipKey="open_interest"
      forceTooltipOpen
    />
  ),
};

export const TooltipOpenAnnPct = {
  name: 'Tooltip Open — Ann.%',
  render: () => (
    <HeaderHarness
      field="annualized_return_pct"
      label="Ann.%"
      tooltipKey="annualized_return_pct"
      forceTooltipOpen
    />
  ),
};

export const WithActiveSortIndicator = {
  render: () => (
    <HeaderHarness
      field="annualized_return_pct"
      label="Ann.%"
      tooltipKey="annualized_return_pct"
      active
    />
  ),
};
