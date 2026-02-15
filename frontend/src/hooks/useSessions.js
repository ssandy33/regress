import { useState, useEffect, useCallback } from 'react';
import toast from 'react-hot-toast';
import { listSessions, createSession, deleteSession, getSession } from '../api/client';

export function useSessions() {
  const [sessions, setSessions] = useState([]);
  const [loading, setLoading] = useState(false);

  const refresh = useCallback(async () => {
    try {
      const data = await listSessions();
      setSessions(data);
    } catch {
      // silently fail — sessions are not critical
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const save = useCallback(async (name, config) => {
    setLoading(true);
    try {
      await createSession(name, config);
      toast.success('Session saved');
      await refresh();
    } catch {
      toast.error('Failed to save session');
    } finally {
      setLoading(false);
    }
  }, [refresh]);

  const remove = useCallback(async (id) => {
    try {
      await deleteSession(id);
      toast.success('Session deleted');
      await refresh();
    } catch {
      toast.error('Failed to delete session');
    }
  }, [refresh]);

  const load = useCallback(async (id) => {
    try {
      const session = await getSession(id);
      return session;
    } catch {
      toast.error('Failed to load session');
      return null;
    }
  }, []);

  return { sessions, loading, save, remove, load, refresh };
}
