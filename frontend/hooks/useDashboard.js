import { useCallback, useEffect, useState } from 'react';
import { getDashboard } from '../api/client';

/**
 * useDashboard — single round-trip fetch for the unified dashboard payload.
 *
 * Returns `{ data, loading, error, refetch }`. Pattern matches `useSchwabStatus`
 * and `useSourceHealth`. Backend composes the response per issue #114 so we
 * don't fan out N+1 calls from the client.
 */
export function useDashboard() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const refetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const payload = await getDashboard();
      setData(payload);
    } catch (e) {
      setError(e?.response?.data?.detail || 'Failed to load dashboard');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return { data, loading, error, refetch };
}
