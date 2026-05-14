// Stories for ScannerStrategyPrimer (issue #190, Affordance 1).
// Fixture data only.

import ScannerStrategyPrimer from './ScannerStrategyPrimer';

// Storybook decorator: prefill localStorage before the component mounts so
// we can demonstrate both the collapsed and expanded states without adding
// a story-only prop to the production component. The component reads
// localStorage in its useState initializer on first render.
function withPrefilledStorage(collapsed) {
  const Decorator = (Story, context) => {
    if (typeof window !== 'undefined') {
      const strategy = context.args.strategy === 'csp' ? 'csp' : 'cc';
      const key = `scanner-primer-collapsed-${strategy}`;
      window.localStorage.setItem(key, collapsed ? '1' : '0');
    }
    return <Story />;
  };
  Decorator.displayName = `WithPrefilledStorage(collapsed=${collapsed})`;
  return Decorator;
}

const meta = {
  title: 'Options/ScannerStrategyPrimer',
  component: ScannerStrategyPrimer,
  parameters: {
    layout: 'padded',
    docs: {
      description: {
        component:
          'Top-of-page strategy primer for the Options Scanner. Collapsed by ' +
          'default, collapse state persisted per strategy in localStorage, ' +
          'reacts to the CC/CSP toggle. See ' +
          '`frontend/design-specs/scanner-education-v0.5.7.md`.',
      },
    },
  },
  argTypes: {
    strategy: { control: { type: 'inline-radio' }, options: ['cc', 'csp'] },
  },
};

export default meta;

export const CoveredCallCollapsed = {
  name: 'Covered Call — Collapsed',
  args: { strategy: 'cc' },
  decorators: [withPrefilledStorage(true)],
};

export const CoveredCallExpanded = {
  name: 'Covered Call — Expanded',
  args: { strategy: 'cc' },
  decorators: [withPrefilledStorage(false)],
};

export const CashSecuredPutExpanded = {
  name: 'Cash-Secured Put — Expanded',
  args: { strategy: 'csp' },
  decorators: [withPrefilledStorage(false)],
};

export const DarkModeExpanded = {
  name: 'Dark Mode — Expanded',
  args: { strategy: 'cc' },
  parameters: {
    themes: { themeOverride: 'dark' },
    backgrounds: { default: 'dark' },
  },
  decorators: [
    withPrefilledStorage(false),
    (Story) => (
      <div className="dark bg-slate-900 p-6 -m-4 min-h-[300px]">
        <Story />
      </div>
    ),
  ],
};
