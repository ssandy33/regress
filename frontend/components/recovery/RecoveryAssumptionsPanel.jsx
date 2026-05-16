// Assumptions audit panel — six rows in fixed order.
//
// Spec: frontend/design-specs/issue-182-recovery-recommendation.md §5.
// The backend emits the full list with labels + values + sources; the
// component just renders the table inside a <details> wrapper.

export default function RecoveryAssumptionsPanel({ assumptions, defaultOpen = false }) {
  if (!assumptions || assumptions.length === 0) return null;
  return (
    <details
      data-testid="recovery-assumptions-panel"
      open={defaultOpen}
      className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800"
    >
      <summary className="cursor-pointer select-none px-4 py-3 text-sm font-medium text-slate-700 dark:text-slate-200">
        Assumptions
      </summary>
      <div className="px-4 pb-4">
        <table className="min-w-full text-sm">
          <thead>
            <tr className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
              <th className="text-left py-2 pr-3">Label</th>
              <th className="text-left py-2 pr-3">Value</th>
              <th className="text-left py-2">Source</th>
            </tr>
          </thead>
          <tbody>
            {assumptions.map((row) => (
              <tr
                key={row.label}
                data-testid={`recovery-assumption-${slugify(row.label)}`}
                className="border-t border-slate-100 dark:border-slate-700/40"
              >
                <td className="py-2 pr-3 text-slate-700 dark:text-slate-200">
                  {row.label}
                </td>
                <td
                  className={
                    row.value === 'Not set'
                      ? 'py-2 pr-3 text-slate-500 dark:text-slate-400 tabular-nums'
                      : 'py-2 pr-3 text-slate-900 dark:text-white tabular-nums'
                  }
                >
                  {row.value}
                </td>
                <td className="py-2 text-xs text-slate-500 dark:text-slate-400">
                  {row.source}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}

function slugify(value) {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
}
