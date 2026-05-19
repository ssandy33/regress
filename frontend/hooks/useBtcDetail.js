import { useCallback, useEffect, useState } from 'react';
import { getBtcDetail } from '../api/client';

/**
 * useBtcDetail — fetch the buy-to-close detail payload for a single leg.
 *
 * Mirrors `useRecoveryPlan` (`{ data, loading, error, refetch }`), with one
 * deliberate difference: a 404 is a *known state* for this screen, not an
 * error. The endpoint 404s for an unknown / closed leg, which drives the
 * `not-found` EmptyState — so the hook converts a 404 into a synthetic
 * `{ state: 'not-found' }` payload rather than surfacing the error banner.
 *
 * Pattern: V1.0.6 / issue #244.
 */
export function useBtcDetail(positionId, legId) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const refetch = useCallback(async () => {
    if (!positionId || !legId) {
      setData(null);
      setLoading(false);
      return;
    }
    // Drop the prior leg's detail before the new fetch resolves.
    setData(null);
    setLoading(true);
    setError(null);
    try {
      const payload = await getBtcDetail(positionId, legId);
      setData(payload);
    } catch (e) {
      if (e?.response?.status === 404) {
        // A 404 is a known state — render the not-found EmptyState, not the
        // error banner. The leg is unknown, closed, or on another position.
        setData({ state: 'not-found' });
      } else {
        setError(
          e?.response?.data?.detail ||
            'Failed to load buy-to-close detail',
        );
      }
    } finally {
      setLoading(false);
    }
  }, [positionId, legId]);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { data, loading, error, refetch };
}
