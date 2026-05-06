import Link from 'next/link';

/**
 * StatusPill — colored dot + label, optionally a navigation target.
 *
 * Used by the dashboard status strip. Follow-up: consolidate the inline
 * status banners in OptionScanner.jsx and SettingsPage.jsx onto this primitive.
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
}) {
  const dot = STATE_CLASSES[state] ?? STATE_CLASSES.neutral;
  const inner = (
    <>
      <span
        className={`inline-block w-2.5 h-2.5 rounded-full ${dot}`}
        aria-hidden="true"
      />
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
        className={`${baseClasses} hover:bg-slate-50 dark:hover:bg-slate-700 transition-colors`}
      >
        {inner}
      </Link>
    );
  }

  return (
    <span data-testid={dataTestid} className={baseClasses}>
      {inner}
    </span>
  );
}
