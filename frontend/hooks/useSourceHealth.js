import { useState, useEffect, useRef } from 'react';
import { checkSourceHealth } from '../api/client';

const POLL_INTERVAL = 5 * 60 * 1000; // 5 minutes

export function useSourceHealth() {
  const [health, setHealth] = useState(null);
  const [allDown, setAllDown] = useState(false);
  const intervalRef = useRef(null);

  const refresh = async () => {
    try {
      const data = await checkSourceHealth();
      setHealth(data);
      setAllDown(data.all_down === true);
    } catch {
      setAllDown(true);
    }
  };

  useEffect(() => {
    let cancelled = false;

    const poll = async () => {
      try {
        const data = await checkSourceHealth();
        if (!cancelled) {
          setHealth(data);
          setAllDown(data.all_down === true);
        }
      } catch {
        if (!cancelled) {
          setAllDown(true);
        }
      }
    };

    poll();
    intervalRef.current = setInterval(poll, POLL_INTERVAL);
    return () => {
      cancelled = true;
      clearInterval(intervalRef.current);
    };
  }, []);

  return { health, allDown, refresh };
}
