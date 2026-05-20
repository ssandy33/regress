import { useCallback, useEffect, useState } from 'react';
import { getCoveredCallView } from '../api/client';

/**
 * useCoveredCallView — fetch the combined covered-call payload for one
 * position. Returns `{ data, loading, error, refetch }` — the same shape
 * `useRecoveryPlan` and `useBtcDetail` expose.
 *
 * The backend owns all branching via the `applicability` flag on the
 * payload (`covered_call` / `not_applicable_no_shares` /
 * `not_applicable_no_short_call` / `not_applicable_closed`), so the hook
 * is dumb and just exposes the payload.
 *
 * Pattern: V1.0.6 / issue #247.
 */
export function useCoveredCallView(positionId) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const refetch = useCallback(async () => {
    if (!positionId) {
      setData(null);
      setLoading(false);
      return;
    }
    // Drop the prior position's view before the new fetch resolves.
    setData(null);
    setLoading(true);
    setError(null);
    try {
      const payload = await getCoveredCallView(positionId);
      setData(payload);
    } catch (e) {
      setError(
        e?.response?.data?.detail || 'Failed to load combined P&L',
      );
    } finally {
      setLoading(false);
    }
  }, [positionId]);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { data, loading, error, refetch };
}
