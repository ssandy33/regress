// Three-variant Recovery Plan recommendation banner.
//
// Variants:
//   - 'recommended'        — blue tint, ✦ glyph, label + bullets, mini-disclaimer
//   - 'no-clear-best-fit'  — slate neutral, = glyph, top-2 list, no card emphasis
//   - 'no-eligible-path'   — amber, ⓘ glyph, suppressed list, Adjust caps → CTA
//
// Spec: frontend/design-specs/issue-182-recovery-recommendation.md §2.
// All copy variants come from the backend's `recommendation.recommendation_label`
// + `recommendation_reasons`; the banner just shapes the chrome.

import Link from 'next/link';

const MINI_DISCLAIMER =
  'This is a fit recommendation against your configured preferences and stated assumptions — not investment advice or a price prediction.';

function deriveState(recommendation) {
  if (!recommendation) return 'recommended';
  if (recommendation.recommended_path_id) return 'recommended';
  if (
    recommendation.recommendation_label === 'No eligible path under current sizing rules'
  ) {
    return 'no-eligible-path';
  }
  return 'no-clear-best-fit';
}

function variantClasses(state) {
  switch (state) {
    case 'no-clear-best-fit':
      return 'rounded-xl border p-5 border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800';
    case 'no-eligible-path':
      return 'rounded-xl border p-5 border-amber-200 dark:border-amber-700 bg-amber-50 dark:bg-amber-900/20';
    case 'recommended':
    default:
      return 'rounded-xl border p-5 border-blue-200 dark:border-blue-700 bg-blue-50 dark:bg-blue-900/20';
  }
}

function variantGlyph(state) {
  switch (state) {
    case 'no-clear-best-fit':
      return { char: '=', cls: 'text-xl text-slate-500' };
    case 'no-eligible-path':
      return { char: 'ⓘ', cls: 'text-xl text-amber-600 dark:text-amber-300' };
    case 'recommended':
    default:
      return { char: '✦', cls: 'text-xl text-blue-600 dark:text-blue-300' };
  }
}

function inspectScoringLink() {
  // Opens (if collapsed) and scrolls to the matrix. Honor reduced motion.
  return () => {
    const matrix = document.querySelector('[data-testid="recovery-scoring-matrix"]');
    if (!matrix) return;
    if (typeof matrix.open !== 'undefined') {
      matrix.open = true;
    }
    const prefersReducedMotion = window.matchMedia?.(
      '(prefers-reduced-motion: reduce)',
    ).matches;
    matrix.scrollIntoView({
      behavior: prefersReducedMotion ? 'auto' : 'smooth',
      block: 'start',
    });
  };
}

export default function RecoveryRecommendationBanner({
  recommendation,
  rankedPaths,
  dataTestid = 'recovery-recommendation-banner',
}) {
  if (!recommendation) return null;
  const state = deriveState(recommendation);
  const glyph = variantGlyph(state);

  return (
    <section
      data-testid={dataTestid}
      data-state={state}
      className={variantClasses(state)}
      aria-label="Recovery plan recommendation"
    >
      <div className="flex items-start gap-3">
        <span aria-hidden="true" className={glyph.cls}>
          {glyph.char}
        </span>
        <div className="flex-1 min-w-0">
          <h2
            data-testid="recovery-recommendation-label"
            className="text-base font-semibold text-slate-900 dark:text-white"
          >
            {recommendation.recommendation_label}
          </h2>

          {state === 'recommended' && recommendation.recommendation_reasons?.length > 0 && (
            <>
              <div className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400 mt-3 mb-2">
                Why this fits
              </div>
              <ul
                data-testid="recovery-recommendation-reasons"
                className="list-disc pl-5 space-y-1"
              >
                {recommendation.recommendation_reasons.map((reason, idx) => (
                  <li
                    key={reason}
                    data-testid={`recovery-recommendation-reason-${idx}`}
                    className="text-sm text-slate-700 dark:text-slate-200"
                  >
                    {reason}
                  </li>
                ))}
              </ul>
            </>
          )}

          {state === 'no-clear-best-fit' && (
            <>
              <p className="text-sm text-slate-700 dark:text-slate-200 mt-2">
                The top two paths score within {recommendation.tie_epsilon} point of each
                other — both are within your configured preferences. The numbers are
                below; the call is yours.
              </p>
              <ul
                data-testid="recovery-recommendation-reasons"
                className="list-disc pl-5 space-y-1 mt-3"
              >
                {(rankedPaths || [])
                  .filter((rp) => rp.rank !== null)
                  .slice(0, 2)
                  .map((rp, idx) => (
                    <li
                      key={rp.path_id}
                      data-testid={`recovery-recommendation-reason-${idx}`}
                      className="text-sm text-slate-700 dark:text-slate-200"
                    >
                      {labelForPath(rp.path_id)} — {rp.score} pts (rank {rp.rank})
                    </li>
                  ))}
              </ul>
            </>
          )}

          {state === 'no-eligible-path' && (
            <>
              <p className="text-sm text-amber-700 dark:text-amber-300 mt-2">
                Every path violates your per-position sizing cap or another
                configured constraint. Adjust your caps in Settings → OKRs, or
                evaluate paths manually using the matrix below.
              </p>
              <ul
                data-testid="recovery-recommendation-reasons"
                className="list-disc pl-5 space-y-1 mt-3"
              >
                {(rankedPaths || []).map((rp, idx) => (
                  <li
                    key={rp.path_id}
                    data-testid={`recovery-recommendation-reason-${idx}`}
                    className="text-sm text-amber-700 dark:text-amber-300"
                  >
                    {labelForPath(rp.path_id)} —{' '}
                    {rp.suppression_reason || '(no specific reason)'}
                  </li>
                ))}
              </ul>
              <div className="mt-3">
                <Link
                  href="/settings#okrs"
                  data-testid="recovery-recommendation-adjust-caps"
                  className="text-sm font-medium text-amber-800 dark:text-amber-200 hover:underline"
                >
                  Adjust caps →
                </Link>
              </div>
            </>
          )}

          <p
            data-testid="recovery-recommendation-disclaimer-inline"
            className="text-xs text-slate-500 dark:text-slate-400 mt-3"
          >
            {MINI_DISCLAIMER}{' '}
            <button
              type="button"
              onClick={inspectScoringLink()}
              className="font-medium text-blue-700 dark:text-blue-300 hover:underline"
            >
              Inspect scoring ▾
            </button>
          </p>
        </div>
      </div>
    </section>
  );
}

const PATH_LABELS = {
  'sell-redeploy': 'Sell & redeploy',
  'wheel-cc': 'Wheel covered calls',
  'average-down': 'Average down',
  'hold-monitor': 'Hold & monitor',
};

function labelForPath(slug) {
  return PATH_LABELS[slug] || slug;
}
