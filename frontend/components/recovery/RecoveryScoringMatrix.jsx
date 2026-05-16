// Full criterion × eligible-path scoring matrix, inside a <details> element
// (collapsed by default per design Q1). Suppressed paths render as a stacked
// footer (not as columns), one entry per path.
//
// Spec: frontend/design-specs/issue-182-recovery-recommendation.md §4.

import Link from 'next/link';

const PATH_LABELS = {
  'sell-redeploy': 'Sell & redeploy',
  'wheel-cc': 'Wheel covered calls',
  'average-down': 'Average down',
  'hold-monitor': 'Hold & monitor',
};

const CRITERION_LABELS = {
  fastest_breakeven: 'Fastest breakeven',
  lowest_additional_capital: 'Lowest add’l capital',
  lowest_opportunity_cost: 'Lowest opp. cost',
  strategy_preference_bonus: 'Strategy preference',
};

const CRITERION_SLUGS = {
  fastest_breakeven: 'fastest-breakeven',
  lowest_additional_capital: 'lowest-additional-capital',
  lowest_opportunity_cost: 'lowest-opportunity-cost',
  strategy_preference_bonus: 'strategy-preference-bonus',
};

function formatRaw(criterion, value) {
  if (value === null || value === undefined) return '—';
  if (criterion === 'fastest_breakeven') {
    return `${value} mo`;
  }
  if (
    criterion === 'lowest_additional_capital'
    || criterion === 'lowest_opportunity_cost'
  ) {
    return `$${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  }
  return '—';
}

function isStrategyPreferenceUnset(row) {
  if (!row || row.criterion !== 'strategy_preference_bonus') return false;
  return (row.ranking || []).every((c) => (c.points || 0) === 0);
}

export default function RecoveryScoringMatrix({
  pathScores,
  rankedPaths,
  paths,
  recommendedPathId,
  tieEpsilon,
  defaultOpen = false,
}) {
  if (!pathScores || pathScores.length === 0) return null;

  // Compute the column order (eligible paths only, in canonical engine order).
  const eligiblePathIds = (paths || [])
    .filter((p) => p.eligibility === 'eligible')
    .map((p) => p.path_id);
  const eligibleLookup = Object.fromEntries(
    (paths || []).map((p) => [p.path_id, p]),
  );

  const totalsByPath = Object.fromEntries(
    (rankedPaths || [])
      .filter((rp) => rp.score !== null && rp.score !== undefined)
      .map((rp) => [rp.path_id, { score: rp.score, rank: rp.rank }]),
  );

  const suppressedRanked = (rankedPaths || []).filter(
    (rp) => rp.score === null,
  );

  return (
    <details
      data-testid="recovery-scoring-matrix"
      open={defaultOpen}
      className="rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-800"
    >
      <summary
        data-testid="recovery-scoring-matrix-summary"
        className="cursor-pointer select-none px-4 py-3 text-sm font-medium text-slate-700 dark:text-slate-200"
      >
        Inspect scoring ({pathScores.length} criteria, {eligiblePathIds.length}{' '}
        eligible paths
        {suppressedRanked.length > 0 ? `, ${suppressedRanked.length} suppressed` : ''}
        )
      </summary>

      <div className="px-4 pb-4">
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 mb-3">
          How each path scored against each criterion. Weights are V0.5.8 defaults
          — these are inputs to a fit calculation, not financial scoring.
        </p>

        <div className="overflow-x-auto">
          <table className="min-w-full text-sm border-collapse">
            <thead>
              <tr className="border-b border-slate-200 dark:border-slate-700">
                <th
                  scope="col"
                  className="text-left text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400 py-2 pr-3 sticky left-0 bg-white dark:bg-slate-800"
                >
                  Criterion (weight)
                </th>
                {eligiblePathIds.map((pid) => (
                  <th
                    key={pid}
                    scope="col"
                    className="text-left text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400 py-2 px-3"
                  >
                    {PATH_LABELS[pid] || eligibleLookup[pid]?.label || pid}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {pathScores.map((row) => {
                const unsetPref = isStrategyPreferenceUnset(row);
                return (
                  <tr
                    key={row.criterion}
                    data-testid={`recovery-scoring-row-${CRITERION_SLUGS[row.criterion] || row.criterion}`}
                    className="border-b border-slate-100 dark:border-slate-700/40"
                  >
                    <th
                      scope="row"
                      className="text-left py-2 pr-3 text-slate-700 dark:text-slate-200 sticky left-0 bg-white dark:bg-slate-800"
                    >
                      {CRITERION_LABELS[row.criterion] || row.criterion}
                      <span className="ml-2 text-xs text-slate-400">×{row.weight}</span>
                      {unsetPref && (
                        <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                          Strategy preference is unset —{' '}
                          <Link
                            href="/settings#okrs"
                            data-testid="recovery-scoring-strategy-preference-link"
                            className="text-blue-700 dark:text-blue-300 hover:underline"
                          >
                            Settings → OKRs
                          </Link>{' '}
                          to activate.
                        </div>
                      )}
                    </th>
                    {eligiblePathIds.map((pid) => {
                      const cell = (row.ranking || []).find(
                        (c) => c.path_id === pid,
                      );
                      const isLeader = cell?.rank === 1 && cell?.points > 0;
                      return (
                        <td
                          key={pid}
                          data-testid={`recovery-scoring-cell-${CRITERION_SLUGS[row.criterion] || row.criterion}-${pid}`}
                          className={
                            'py-2 px-3 text-slate-700 dark:text-slate-200 '
                            + (isLeader
                              ? 'bg-blue-50 dark:bg-blue-900/10'
                              : '')
                          }
                        >
                          {cell ? (
                            <>
                              <span className="tabular-nums">
                                {formatRaw(row.criterion, cell.raw_value)}
                              </span>
                              <span className="text-slate-400 mx-1">·</span>
                              <span className="font-medium">{cell.points} pts</span>
                              {isLeader && (
                                <span
                                  aria-hidden="true"
                                  className="ml-1 text-blue-600 dark:text-blue-300"
                                >
                                  ✦
                                </span>
                              )}
                            </>
                          ) : (
                            '—'
                          )}
                        </td>
                      );
                    })}
                  </tr>
                );
              })}

              <tr className="border-t-2 border-slate-200 dark:border-slate-700">
                <th
                  scope="row"
                  className="text-left py-2 pr-3 text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400 sticky left-0 bg-white dark:bg-slate-800"
                >
                  Total
                </th>
                {eligiblePathIds.map((pid) => {
                  const total = totalsByPath[pid];
                  const recommended = pid === recommendedPathId;
                  return (
                    <td
                      key={pid}
                      data-testid={`recovery-scoring-total-${pid}`}
                      className={
                        'py-2 px-3 font-medium '
                        + (recommended
                          ? 'text-blue-700 dark:text-blue-300'
                          : 'text-slate-700 dark:text-slate-200')
                      }
                    >
                      {total ? `${total.score} pts` : '—'}
                      {recommended && (
                        <span aria-hidden="true" className="ml-1">
                          ✦
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
              <tr>
                <th
                  scope="row"
                  className="text-left py-2 pr-3 text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400 sticky left-0 bg-white dark:bg-slate-800"
                >
                  Rank
                </th>
                {eligiblePathIds.map((pid) => {
                  const total = totalsByPath[pid];
                  const recommended = pid === recommendedPathId;
                  return (
                    <td
                      key={pid}
                      data-testid={`recovery-scoring-rank-${pid}`}
                      className="py-2 px-3 text-slate-700 dark:text-slate-200"
                    >
                      {total ? total.rank : '—'}
                      {recommended && (
                        <span className="ml-1 text-xs text-blue-700 dark:text-blue-300">
                          (recommended)
                        </span>
                      )}
                    </td>
                  );
                })}
              </tr>
            </tbody>
          </table>
        </div>

        {suppressedRanked.length > 0 && (
          <div className="mt-3 p-3 rounded-lg bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-700">
            <div className="text-xs uppercase tracking-wide text-amber-700 dark:text-amber-300 mb-1">
              Suppressed
            </div>
            <ul className="space-y-1">
              {suppressedRanked.map((rp) => (
                <li
                  key={rp.path_id}
                  data-testid={`recovery-scoring-suppressed-${rp.path_id}`}
                  className="text-sm text-amber-700 dark:text-amber-300"
                >
                  {PATH_LABELS[rp.path_id] || rp.path_id} —{' '}
                  {rp.suppression_reason || '(no reason provided)'}
                </li>
              ))}
            </ul>
          </div>
        )}

        <p className="text-xs text-slate-500 dark:text-slate-400 mt-3">
          Weights are V0.5.8 defaults. Points are awarded per criterion based on
          rank; ties within {tieEpsilon} total points are flagged as “no clear best fit.”
        </p>
      </div>
    </details>
  );
}
