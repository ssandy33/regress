import { useCallback, useEffect, useState } from 'react';
import { getRecoveryPlan } from '../api/client';

/**
 * useRecoveryPlan — fetch the Recovery Plan payload for a single position.
 *
 * Mirrors `useDashboard`: returns `{ data, loading, error, refetch }`. The
 * backend handles all branching (not-applicable, not-flagged, populated),
 * so the hook is dumb and just exposes the payload.
 *
 * Pattern: V0.5.8 / issue #182.
 */
export function useRecoveryPlan(positionId) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const refetch = useCallback(async () => {
    if (!positionId) {
      // Clear any previously-loaded plan so a stale position never lingers.
      setData(null);
      setLoading(false);
      return;
    }
    // Drop the prior position's plan before the new fetch resolves.
    setData(null);
    setLoading(true);
    setError(null);
    try {
      const payload = await getRecoveryPlan(positionId);
      setData(payload);
    } catch (e) {
      setError(e?.response?.data?.detail || 'Failed to load recovery plan');
    } finally {
      setLoading(false);
    }
  }, [positionId]);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { data, loading, error, refetch };
}
