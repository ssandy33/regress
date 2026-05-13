// Phase 1.5 mock — placeholder for spec implementation. Replace during Phase 3.
//
// Stories for ScannerStrategyPrimer (issue #190, Affordance 1).
// Fixture data only.

import ScannerStrategyPrimer from './ScannerStrategyPrimer';

const meta = {
  title: 'Options/ScannerStrategyPrimer',
  component: ScannerStrategyPrimer,
  parameters: {
    layout: 'padded',
    docs: {
      description: {
        component:
          'Top-of-page strategy primer for the Options Scanner. Collapsed by ' +
          'default, persisted dismissal per strategy in localStorage, reacts ' +
          'to the CC/CSP toggle. See `frontend/design-specs/scanner-education-v0.5.7.md`.',
      },
    },
  },
  argTypes: {
    strategy: { control: { type: 'inline-radio' }, options: ['cc', 'csp'] },
    defaultExpanded: { control: 'boolean' },
  },
};

export default meta;

export const CoveredCallCollapsed = {
  name: 'Covered Call — Collapsed',
  args: {
    strategy: 'cc',
    defaultExpanded: false,
  },
};

export const CoveredCallExpanded = {
  name: 'Covered Call — Expanded',
  args: {
    strategy: 'cc',
    defaultExpanded: true,
  },
};

export const CashSecuredPutExpanded = {
  name: 'Cash-Secured Put — Expanded',
  args: {
    strategy: 'csp',
    defaultExpanded: true,
  },
};

// Pinned dark-mode story — designer mental-checked color contrast in dark.
// To verify visually, also toggle the toolbar theme to "dark" on any story.
export const DarkModeExpanded = {
  name: 'Dark Mode — Expanded',
  args: {
    strategy: 'cc',
    defaultExpanded: true,
  },
  parameters: {
    themes: { themeOverride: 'dark' },
    backgrounds: { default: 'dark' },
  },
  decorators: [
    (Story) => (
      <div className="dark bg-slate-900 p-6 -m-4 min-h-[300px]">
        <Story />
      </div>
    ),
  ],
};
