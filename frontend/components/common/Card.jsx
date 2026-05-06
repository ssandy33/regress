/**
 * Card — shared shell for dashboard sections.
 *
 * Wraps the existing inline pattern (`bg-white dark:bg-slate-800 ...`) used in
 * 8+ places across the app. Designed to be extended by `components/dashboard/*`
 * cards. Existing call sites are not migrated in this PR — see the follow-up
 * issue to consolidate inline usages.
 */
export default function Card({
  title,
  description,
  footer,
  className = '',
  contentClassName = '',
  dataTestid,
  children,
}) {
  return (
    <section
      data-testid={dataTestid}
      className={`bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-xl ${className}`}
    >
      {(title || description) && (
        <header className="px-4 pt-4 pb-3 border-b border-slate-200 dark:border-slate-700">
          {title && (
            <h3 className="text-lg font-semibold text-slate-900 dark:text-white">
              {title}
            </h3>
          )}
          {description && (
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              {description}
            </p>
          )}
        </header>
      )}
      <div className={`p-4 ${contentClassName}`}>{children}</div>
      {footer && (
        <footer className="px-4 py-3 border-t border-slate-200 dark:border-slate-700 text-sm text-slate-500 dark:text-slate-400">
          {footer}
        </footer>
      )}
    </section>
  );
}
