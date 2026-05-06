import Link from 'next/link';

/**
 * EmptyState — center-aligned empty/onboarding block.
 *
 * Each action accepts either {label, href} for navigation or {label, onClick}
 * for inline behavior. Up to two actions render side-by-side.
 */
function ActionButton({ action, primary }) {
  if (!action) return null;
  const className = primary
    ? 'inline-flex items-center px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700'
    : 'inline-flex items-center px-4 py-2 rounded-lg border border-slate-300 dark:border-slate-600 text-sm font-medium text-slate-700 dark:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-700';
  if (action.href) {
    return (
      <Link href={action.href} className={className}>
        {action.label}
      </Link>
    );
  }
  return (
    <button type="button" onClick={action.onClick} className={className}>
      {action.label}
    </button>
  );
}

export default function EmptyState({
  icon,
  title,
  description,
  primaryAction,
  secondaryAction,
  dataTestid,
}) {
  return (
    <div
      data-testid={dataTestid}
      className="text-center py-8 px-4"
    >
      {icon && <div className="mx-auto mb-3 text-slate-300 dark:text-slate-600">{icon}</div>}
      {title && (
        <h4 className="text-base font-medium text-slate-700 dark:text-slate-200 mb-1">
          {title}
        </h4>
      )}
      {description && (
        <p className="text-sm text-slate-500 dark:text-slate-400 max-w-md mx-auto">
          {description}
        </p>
      )}
      {(primaryAction || secondaryAction) && (
        <div className="mt-4 flex items-center justify-center gap-3">
          <ActionButton action={primaryAction} primary />
          <ActionButton action={secondaryAction} />
        </div>
      )}
    </div>
  );
}
