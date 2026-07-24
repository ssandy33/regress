import Link from 'next/link';

/**
 * StatusPill — colored dot + label, optionally a navigation target.
 *
 * Used by the dashboard status strip. Follow-up: consolidate the inline
 * status banners in OptionScanner.jsx and SettingsPage.jsx onto this primitive.
 *
 * ``title`` sets a native hover tooltip (e.g. the freshness pill's stalest-quote
 * detail, #417). ``dataAttrs`` is an object of extra ``data-*`` attributes spread
 * onto the rendered element (e.g. ``{ 'data-freshness-state': 'stale' }``) so
 * callers can attach frozen test/contract attributes without bloating the
 * primitive's prop list.
 *
 * ``variant`` (#437): ``'status'`` (default) renders the colored health dot.
 * ``'count'`` renders a numeric badge instead of a dot — for INFORMATIONAL
 * counts (e.g. the journal position count) that share the strip but are NOT
 * health signals. A grey status dot in a row of green health dots reads as
 * "degraded"; the count badge makes "this is a tally, not a status" explicit.
 */
const STATE_CLASSES = {
  ok: 'bg-emerald-500',
  warn: 'bg-yellow-500',
  error: 'bg-red-500',
  neutral: 'bg-slate-400',
};

export default function StatusPill({
  state = 'neutral',
  label,
  href,
  dataTestid,
  title,
  dataAttrs = {},
  variant = 'status',
  count,
}) {
  const dot = STATE_CLASSES[state] ?? STATE_CLASSES.neutral;
  const marker =
    variant === 'count' ? (
      // The number is meaningful content (a tally), so it stays readable to
      // assistive tech — unlike the health dot, whose color carries nothing.
      <span className="inline-flex items-center justify-center min-w-[1.25rem] h-5 px-1.5 rounded-full bg-slate-100 dark:bg-slate-700 text-slate-700 dark:text-slate-200 text-xs font-semibold tabular-nums">
        {count}
      </span>
    ) : (
      <span
        className={`inline-block w-2.5 h-2.5 rounded-full ${dot}`}
        aria-hidden="true"
      />
    );
  const inner = (
    <>
      {marker}
      <span className="text-sm text-slate-700 dark:text-slate-200">{label}</span>
    </>
  );

  const baseClasses =
    'inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800';

  if (href) {
    return (
      <Link
        href={href}
        data-testid={dataTestid}
        title={title}
        className={`${baseClasses} hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors`}
        {...dataAttrs}
      >
        {inner}
      </Link>
    );
  }

  return (
    <span data-testid={dataTestid} title={title} className={baseClasses} {...dataAttrs}>
      {inner}
    </span>
  );
}
