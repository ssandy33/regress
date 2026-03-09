import { useState, useEffect } from 'react';
import { checkSchwabHealth } from '../api/client';

export function useSchwabStatus() {
  const [status, setStatus] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;

    async function fetchStatus() {
      try {
        const data = await checkSchwabHealth();
        if (!cancelled) setStatus(data);
      } catch {
        if (!cancelled) setStatus({ configured: false, valid: false, error: 'Unable to check status' });
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchStatus();
    return () => { cancelled = true; };
  }, []);

  const isAvailable = status?.configured && status?.valid;

  return { status, loading, isAvailable };
}
