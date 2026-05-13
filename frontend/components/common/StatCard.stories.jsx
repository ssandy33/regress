import StatCard from './StatCard';

/**
 * StatCard is the labeled metric tile used across the dashboard KPI row and
 * the regression results panel. Variants below mirror the real UI states the
 * component renders in production.
 *
 * Fixture data only — no API calls, no live data sources.
 */
const meta = {
  title: 'Common/StatCard',
  component: StatCard,
  parameters: {
    layout: 'centered',
  },
  // The component is presentational; we drive all variants via `args`.
  argTypes: {
    label: { control: 'text' },
    value: { control: 'text' },
    subtext: { control: 'text' },
    tooltip: { control: 'text' },
    colorClass: { control: 'text' },
  },
};

export default meta;

export const Default = {
  args: {
    label: 'Open positions',
    value: '7',
    subtext: '3 wheels, 4 holdings',
  },
};

// StatCard has no built-in `loading` prop; the dashboard renders a skeleton
// by passing an em-dash while data is in flight. This story models that.
export const Loading = {
  args: {
    label: 'Open positions',
    value: '—',
    subtext: 'Loading…',
  },
};

export const Empty = {
  args: {
    label: 'Open positions',
    value: '—',
    subtext: 'No data',
  },
};

export const Positive = {
  args: {
    label: 'Realized P/L (MTD)',
    value: '+$1,234.56',
    subtext: '+2.5% vs. last month',
    colorClass: 'text-emerald-600 dark:text-emerald-400',
  },
};

export const Negative = {
  args: {
    label: 'Realized P/L (MTD)',
    value: '-$842.10',
    subtext: '-1.8% vs. last month',
    colorClass: 'text-rose-600 dark:text-rose-400',
  },
};

export const WithTooltip = {
  args: {
    label: 'Win rate',
    value: '64%',
    subtext: '32 / 50 closed trades',
    tooltip: 'Trades closed at or above cost basis',
  },
};
