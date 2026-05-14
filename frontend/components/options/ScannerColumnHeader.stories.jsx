// Stories for ScannerColumnHeader (issue #190, Affordance 2).
// Wraps the header in a real <table> shell so the tooltip positioning and
// sort affordance are inspectable in the same context they ship in.

import ScannerColumnHeader from './ScannerColumnHeader';
import { SCANNER_COLUMN_TOOLTIPS } from './scannerColumnTooltips';

const TOOLTIPS = {
  delta: SCANNER_COLUMN_TOOLTIPS.delta,
  open_interest: SCANNER_COLUMN_TOOLTIPS.open_interest,
  annualized_return_pct: SCANNER_COLUMN_TOOLTIPS.annualized_return_pct,
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
