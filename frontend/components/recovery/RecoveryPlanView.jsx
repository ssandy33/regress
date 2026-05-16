// Composition surface for the populated Recovery Plan state.
//
// Renders: banner (top) → 4-up card grid (middle) → scoring matrix
// (collapsed) → assumptions (collapsed) → persistent disclaimer (footer).
//
// Spec: frontend/design-specs/issue-182-recovery-recommendation.md §1.

import RecoveryRecommendationBanner from './RecoveryRecommendationBanner';
import RecoveryPathCard from './RecoveryPathCard';
import RecoveryScoringMatrix from './RecoveryScoringMatrix';
import RecoveryAssumptionsPanel from './RecoveryAssumptionsPanel';

export default function RecoveryPlanView({ data }) {
  if (!data) return null;
  const { paths = [], recommendation, assumptions = [], disclaimer } = data;
  const recommendedId = recommendation?.recommended_path_id || null;

  return (
    <div className="space-y-6">
      <RecoveryRecommendationBanner
        recommendation={recommendation}
        rankedPaths={recommendation?.ranked_paths || []}
      />

      <div>
        <h3 className="text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400 mb-2">
          Compare paths
        </h3>
        <div
          data-testid="recovery-path-grid"
          className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4"
        >
          {paths.map((path) => (
            <RecoveryPathCard
              key={path.path_id}
              path={path}
              isRecommended={path.path_id === recommendedId}
            />
          ))}
        </div>
      </div>

      <RecoveryScoringMatrix
        pathScores={recommendation?.path_scores || []}
        rankedPaths={recommendation?.ranked_paths || []}
        paths={paths}
        recommendedPathId={recommendedId}
        tieEpsilon={recommendation?.tie_epsilon}
      />

      <RecoveryAssumptionsPanel assumptions={assumptions} />

      <footer
        data-testid="recovery-disclaimer"
        className="mt-8 p-4 rounded-lg bg-slate-100 dark:bg-slate-800/40 border border-slate-200 dark:border-slate-700"
        aria-label="Recovery plan disclaimer"
      >
        <p
          data-testid="recovery-disclaimer-text"
          className="text-xs text-slate-500 dark:text-slate-400 max-w-prose mx-auto"
        >
          {disclaimer}
        </p>
      </footer>
    </div>
  );
}
