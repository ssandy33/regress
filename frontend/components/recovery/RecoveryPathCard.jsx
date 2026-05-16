// Per-path comparison card for the Recovery Plan grid.
//
// Three treatments:
//   - default              — neutral border, full opacity
//   - recommended          — blue ring + ✦ Recommended pill
//   - suppressed           — dashed border, 70% opacity, amber inline reason
//
// Spec: frontend/design-specs/issue-182-recovery-recommendation.md §3.

import Link from 'next/link';
import { suppressionReasonToCta } from './suppressionReasonCta';

function formatDollar(value) {
  if (value === null || value === undefined || Number.isNaN(value)) return '—';
  const abs = Math.abs(value);
  const sign = value < 0 ? '-' : '';
  return `${sign}$${abs.toLocaleString(undefined, {
    maximumFractionDigits: 0,
  })}`;
}

function formatMonths(value) {
  if (value === null || value === undefined) return '—';
  if (Number.isInteger(value)) return `${value} mo`;
  return `${value} mo`;
}

function opportunityCostColor(slug, value) {
  if (slug === 'sell-redeploy') return 'text-slate-500';
  if (value === null || value === undefined) return 'text-slate-500';
  if (value > 0) return 'text-rose-600 dark:text-rose-400';
  if (value < 0) return 'text-emerald-600 dark:text-emerald-400';
  return 'text-slate-500';
}

function opportunityCostSuffix(slug) {
  return slug === 'sell-redeploy' ? '(baseline)' : '/ yr vs baseline';
}

function keyAssumption(path) {
  if (!path.assumptions || path.assumptions.length === 0) return null;
  // Surface the first assumption (engine emits the most-load-bearing one first).
  return path.assumptions[0];
}

export default function RecoveryPathCard({ path, isRecommended }) {
  const slug = path.path_id;
  const suppressed = path.eligibility === 'suppressed';
  const months = path.months_to_breakeven || {};
  const cta = suppressed ? suppressionReasonToCta(path.suppression_reason) : null;

  const shell = [
    'relative rounded-xl p-4 transition',
    suppressed
      ? 'bg-slate-50 dark:bg-slate-800/60 border border-dashed border-slate-300 dark:border-slate-600 opacity-70'
      : 'bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700',
    isRecommended && !suppressed ? 'ring-2 ring-blue-500/40' : '',
  ]
    .filter(Boolean)
    .join(' ');

  const ariaLabel = suppressed
    ? `${path.label} — suppressed: ${path.suppression_reason || 'not eligible'}`
    : isRecommended
    ? `${path.label} — recommended path`
    : path.label;

  return (
    <article
      data-testid={`recovery-path-card-${slug}`}
      data-eligibility={path.eligibility}
      data-recommended={isRecommended ? 'true' : 'false'}
      aria-label={ariaLabel}
      className={shell}
    >
      {isRecommended && !suppressed && (
        <span
          data-testid={`recovery-path-card-${slug}-recommended-badge`}
          className="absolute top-3 right-3 inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300"
        >
          <span aria-hidden="true">✦</span> Recommended
        </span>
      )}

      <h3 className="text-base font-semibold text-slate-900 dark:text-white pr-24">
        {path.label}
      </h3>

      <div className="mt-3">
        <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
          Capital tied up
        </div>
        <div
          data-testid={`recovery-path-card-${slug}-capital`}
          className={
            suppressed
              ? 'text-2xl font-semibold tabular-nums text-slate-400 dark:text-slate-500'
              : 'text-3xl font-semibold tabular-nums text-slate-900 dark:text-white'
          }
        >
          {suppressed ? '—' : formatDollar(path.capital_tied_up)}
        </div>
      </div>

      <div className="mt-3">
        <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
          {slug === 'hold-monitor' ? 'Breakeven' : 'Months to breakeven'}
        </div>
        {suppressed ? (
          <div className="text-2xl font-semibold text-slate-400 dark:text-slate-500">—</div>
        ) : slug === 'hold-monitor' ? (
          <div
            data-testid={`recovery-path-card-${slug}-breakeven-expected`}
            className="text-sm text-slate-500 dark:text-slate-400 italic mt-1"
          >
            — Hold does not breakeven without action.
          </div>
        ) : (
          <div className="space-y-1 mt-1">
            <RangeRow
              label="best"
              value={formatMonths(months.best)}
              testId={`recovery-path-card-${slug}-breakeven-best`}
            />
            <RangeRow
              label="expected"
              value={formatMonths(months.expected)}
              testId={`recovery-path-card-${slug}-breakeven-expected`}
            />
            <RangeRow
              label="worst"
              value={formatMonths(months.worst)}
              testId={`recovery-path-card-${slug}-breakeven-worst`}
            />
          </div>
        )}
      </div>

      <div className="mt-3">
        <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
          Opportunity cost
        </div>
        <div
          data-testid={`recovery-path-card-${slug}-opp-cost`}
          className={
            suppressed
              ? 'text-2xl font-semibold text-slate-400 dark:text-slate-500'
              : `text-base font-medium tabular-nums ${opportunityCostColor(
                  slug,
                  path.opportunity_cost_vs_baseline,
                )}`
          }
        >
          {suppressed ? (
            '—'
          ) : (
            <>
              {formatDollar(path.opportunity_cost_vs_baseline)}{' '}
              <span className="text-xs text-slate-500 dark:text-slate-400">
                {opportunityCostSuffix(slug)}
              </span>
            </>
          )}
        </div>
      </div>

      {suppressed && (
        <div
          data-testid={`recovery-path-card-${slug}-suppression`}
          className="mt-3 p-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700 text-sm text-amber-700 dark:text-amber-300"
        >
          <span aria-hidden="true" className="text-amber-600 mr-1">
            ⚠
          </span>
          {path.suppression_reason}
          {cta && (
            <div className="mt-2">
              <Link
                href={cta.href}
                data-testid={`recovery-path-card-${slug}-suppression-cta`}
                className="text-amber-800 dark:text-amber-200 font-medium hover:underline"
              >
                {cta.label}
              </Link>
            </div>
          )}
        </div>
      )}

      {!suppressed && keyAssumption(path) && (
        <p
          data-testid={`recovery-path-card-${slug}-assumption`}
          className="text-xs italic text-slate-500 dark:text-slate-400 mt-3"
        >
          {keyAssumption(path)}
        </p>
      )}

      <div
        data-testid={`recovery-narration-${slug}`}
        className="min-h-[3rem] mt-3"
        aria-hidden="true"
      />
    </article>
  );
}

function RangeRow({ label, value, testId }) {
  return (
    <div className="flex items-center gap-2">
      <span aria-hidden="true" className="text-slate-300 dark:text-slate-600">
        ▎
      </span>
      <span className="text-sm text-slate-500 dark:text-slate-400 w-24">{label}</span>
      <span
        data-testid={testId}
        className="text-base font-medium tabular-nums text-slate-700 dark:text-slate-200"
      >
        {value}
      </span>
    </div>
  );
}
