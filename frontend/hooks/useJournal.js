import { useState, useCallback, useEffect } from 'react';
import toast from 'react-hot-toast';
import {
  listPositions,
  getPosition,
  createPosition,
  updatePosition,
  createTrade,
  updateTrade,
  deleteTrade,
} from '../api/client';

export function useJournal() {
  const [positions, setPositions] = useState([]);
  const [selectedPosition, setSelectedPosition] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const fetchPositions = useCallback(async (status = null) => {
    setLoading(true);
    setError(null);
    try {
      const data = await listPositions(status);
      setPositions(data);
    } catch {
      const msg = 'Failed to load positions';
      setError(msg);
      toast.error(msg);
    } finally {
      setLoading(false);
    }
  }, []);

  const selectPosition = useCallback(async (id) => {
    try {
      const data = await getPosition(id);
      setSelectedPosition(data);
    } catch {
      toast.error('Failed to load position details');
    }
  }, []);

  const clearSelection = useCallback(() => {
    setSelectedPosition(null);
  }, []);

  const addPosition = useCallback(async (data) => {
    try {
      await createPosition(data);
      toast.success('Position created');
      await fetchPositions();
    } catch {
      toast.error('Failed to create position');
    }
  }, [fetchPositions]);

  const editPosition = useCallback(async (id, data) => {
    try {
      await updatePosition(id, data);
      toast.success('Position updated');
      await fetchPositions();
      const updated = await getPosition(id);
      setSelectedPosition(updated);
    } catch {
      toast.error('Failed to update position');
    }
  }, [fetchPositions]);

  const addTrade = useCallback(async (data) => {
    try {
      await createTrade(data);
      toast.success('Trade logged');
      if (data.position_id) {
        const updated = await getPosition(data.position_id);
        setSelectedPosition(updated);
      }
    } catch {
      toast.error('Failed to log trade');
    }
  }, []);

  const editTrade = useCallback(async (id, data) => {
    try {
      await updateTrade(id, data);
      toast.success('Trade updated');
      if (selectedPosition) {
        const updated = await getPosition(selectedPosition.id);
        setSelectedPosition(updated);
      }
    } catch {
      toast.error('Failed to update trade');
    }
  }, [selectedPosition]);

  const removeTrade = useCallback(async (id) => {
    try {
      await deleteTrade(id);
      toast.success('Trade deleted');
      if (selectedPosition) {
        const updated = await getPosition(selectedPosition.id);
        setSelectedPosition(updated);
      }
    } catch {
      toast.error('Failed to delete trade');
    }
  }, [selectedPosition]);

  useEffect(() => {
    fetchPositions();
  }, [fetchPositions]);

  return {
    positions,
    selectedPosition,
    loading,
    error,
    fetchPositions,
    selectPosition,
    clearSelection,
    addPosition,
    editPosition,
    addTrade,
    editTrade,
    removeTrade,
  };
}
