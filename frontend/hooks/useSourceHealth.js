import { useState, useEffect, useCallback, useRef } from 'react';
import { checkSourceHealth } from '../api/client';

const POLL_INTERVAL = 5 * 60 * 1000; // 5 minutes

export function useSourceHealth() {
  const [health, setHealth] = useState(null);
  const [allDown, setAllDown] = useState(false);
  const intervalRef = useRef(null);

  const refresh = useCallback(async () => {
    try {
      const data = await checkSourceHealth();
      setHealth(data);
      setAllDown(data.all_down === true);
    } catch {
      // If we can't reach our own backend, consider all down
      setAllDown(true);
    }
  }, []);

  useEffect(() => {
    refresh();
    intervalRef.current = setInterval(refresh, POLL_INTERVAL);
    return () => clearInterval(intervalRef.current);
  }, [refresh]);

  return { health, allDown, refresh };
}
