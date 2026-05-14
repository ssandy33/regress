// Sortable table header cell with a dedicated info-icon tooltip trigger.
//
// Why a dedicated icon (not hover-anywhere on the header): the header cell
// already owns the click-to-sort affordance. Conflating tooltip and sort
// would be ambiguous on touch devices. The `ⓘ` button has its own hit target
// and is keyboard-reachable independently of the sort click.
//
// Tooltip content is 3-part: definition / good range / why it matters.
//
// Spec: frontend/design-specs/scanner-education-v0.5.7.md (Affordance 2)

import { useEffect, useRef, useState } from 'react';

export default function ScannerColumnHeader({
  field,
  label,
  tooltip, // { definition, range, whyItMatters } | null
  active = false,
  sortDir = 'asc',
  onSort,
  align = 'right',
  /**
   * Story-only escape hatch — Storybook uses this to render the tooltip in
   * its open state without simulating a click. Do not set this in production
   * code; use the user-driven toggle via the ⓘ button instead.
   */
  forceTooltipOpen = false,
}) {
  const [open, setOpen] = useState(false);
  const tooltipRef = useRef(null);
  const isOpen = open || forceTooltipOpen;

  // Close on outside click and on Escape. Effect only adds/removes listeners;
  // it never calls setState in its body — setState happens inside the event
  // handlers, which is allowed.
  useEffect(() => {
    if (!isOpen) return undefined;
    const handleClickOutside = (event) => {
      if (tooltipRef.current && !tooltipRef.current.contains(event.target)) {
        setOpen(false);
      }
    };
    const handleEscape = (event) => {
      if (event.key === 'Escape') setOpen(false);
    };
    document.addEventListener('mousedown', handleClickOutside);
    document.addEventListener('keydown', handleEscape);
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
      document.removeEventListener('keydown', handleEscape);
    };
  }, [isOpen]);

  return (
    <th
      scope="col"
      className={`px-3 py-2 text-${align} text-xs font-medium text-slate-500 dark:text-slate-400 select-none relative`}
    >
      <span className="inline-flex items-center gap-1" ref={tooltipRef}>
        {onSort ? (
          <button
            type="button"
            onClick={() => onSort(field)}
            data-testid={`scanner-col-sort-${field}`}
            className="hover:text-slate-700 dark:hover:text-slate-200 focus:outline-none focus:ring-2 focus:ring-blue-500 rounded"
            aria-label={`Sort by ${label}`}
          >
            {label}
            {active && (
              <span className="ml-0.5" aria-hidden="true">
                {sortDir === 'asc' ? '↑' : '↓'}
              </span>
            )}
          </button>
        ) : (
          <span data-testid={`scanner-col-label-${field}`}>{label}</span>
        )}
        {tooltip && (
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            data-testid={`scanner-col-info-${field}`}
            className="w-4 h-4 inline-flex items-center justify-center rounded-full border border-slate-300 dark:border-slate-600 text-[10px] text-slate-500 dark:text-slate-400 hover:text-blue-600 dark:hover:text-blue-300 hover:border-blue-400 dark:hover:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500 cursor-help"
            aria-label={`What is ${label}?`}
            aria-expanded={isOpen}
            aria-describedby={isOpen ? `scanner-col-tooltip-${field}` : undefined}
          >
            i
          </button>
        )}
      </span>
      {isOpen && tooltip && (
        <div
          id={`scanner-col-tooltip-${field}`}
          data-testid={`scanner-col-tooltip-${field}`}
          role="tooltip"
          className={`absolute z-20 top-full mt-1 ${align === 'right' ? 'right-0' : 'left-0'} w-64 bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg shadow-lg p-3 text-left text-xs text-slate-700 dark:text-slate-200 space-y-2 font-normal normal-case`}
        >
          <div>
            <p className="font-semibold text-slate-900 dark:text-white">What it is</p>
            <p>{tooltip.definition}</p>
          </div>
          <div>
            <p className="font-semibold text-slate-900 dark:text-white">Good range</p>
            <p>{tooltip.range}</p>
          </div>
          <div>
            <p className="font-semibold text-slate-900 dark:text-white">Why it matters</p>
            <p>{tooltip.whyItMatters}</p>
          </div>
        </div>
      )}
    </th>
  );
}
