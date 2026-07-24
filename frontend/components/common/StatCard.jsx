/**
 * StatCard — labeled metric tile used in the dashboard KPI row.
 *
 * Hoisted from the inline `StatCard` in StatsPanel.jsx so the dashboard and
 * the regression results panel can share a visual recipe. Adds an optional
 * `subtext` prop for the dashboard's two-line tiles ("3 stock · 1 cash").
 *
 * `footer` renders inside the bordered box, below the subtext — a slot for
 * tile-local affordances (e.g. the reconcile badge, #436) that must live
 * WITHIN the card border, not escape below it. `h-full` lets the tile stretch
 * to the grid row height so a row of StatCards shares one baseline even when
 * one tile carries a footer.
 */
export default function StatCard({
  label,
  value,
  subtext,
  tooltip,
  colorClass,
  dataTestid,
  dataAttrs,
  footer,
}) {
  return (
    <div
      data-testid={dataTestid}
      {...(dataAttrs || {})}
      className="h-full bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg p-4 relative group"
    >
      <div className="text-xs text-slate-500 dark:text-slate-400 mb-1">{label}</div>
      <div
        className={`text-2xl font-semibold ${
          colorClass || 'text-slate-900 dark:text-white'
        }`}
      >
        {value}
      </div>
      {subtext && (
        <div className="text-xs text-slate-500 dark:text-slate-400 mt-1">
          {subtext}
        </div>
      )}
      {footer}
      {tooltip && (
        <div className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-2 bg-slate-800 dark:bg-slate-600 text-white text-xs rounded-lg opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap z-10">
          {tooltip}
        </div>
      )}
    </div>
  );
}
