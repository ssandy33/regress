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
  previewSchwabImport,
  executeSchwabImport,
} from '../api/client';

export function useJournal() {
  const [positions, setPositions] = useState([]);
  const [selectedPosition, setSelectedPosition] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [importPreview, setImportPreview] = useState(null);
  const [importLoading, setImportLoading] = useState(false);

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
      await fetchPositions();
      if (data.position_id) {
        const updated = await getPosition(data.position_id);
        setSelectedPosition(updated);
      }
    } catch {
      toast.error('Failed to log trade');
    }
  }, [fetchPositions]);

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
      await fetchPositions();
      if (selectedPosition) {
        const updated = await getPosition(selectedPosition.id);
        setSelectedPosition(updated);
      }
    } catch {
      toast.error('Failed to delete trade');
    }
  }, [selectedPosition, fetchPositions]);

  const previewImport = useCallback(async (startDate, endDate) => {
    setImportLoading(true);
    try {
      const data = await previewSchwabImport(startDate, endDate);
      setImportPreview(data);
      return data;
    } catch (err) {
      const detail = err?.response?.data?.detail;
      if (err?.response?.status === 401) {
        toast.error(detail || 'Schwab authentication required. Run schwab-auth CLI to connect.');
      } else {
        toast.error(detail || 'Failed to preview Schwab import');
      }
      return null;
    } finally {
      setImportLoading(false);
    }
  }, []);

  const confirmImport = useCallback(async (startDate, endDate, positionStrategy = 'wheel') => {
    setImportLoading(true);
    try {
      const result = await executeSchwabImport(startDate, endDate, positionStrategy);
      toast.success(`Imported ${result.imported} trades`);
      setImportPreview(null);
      await fetchPositions();
      return result;
    } catch (err) {
      const detail = err?.response?.data?.detail;
      if (err?.response?.status === 401) {
        toast.error(detail || 'Schwab authentication required. Run schwab-auth CLI to connect.');
      } else {
        toast.error(detail || 'Failed to import trades');
      }
      return null;
    } finally {
      setImportLoading(false);
    }
  }, [fetchPositions]);

  const clearImportPreview = useCallback(() => {
    setImportPreview(null);
  }, []);

  useEffect(() => {
    fetchPositions();
  }, [fetchPositions]);

  return {
    positions,
    selectedPosition,
    loading,
    error,
    importPreview,
    importLoading,
    fetchPositions,
    selectPosition,
    clearSelection,
    addPosition,
    editPosition,
    addTrade,
    editTrade,
    removeTrade,
    previewImport,
    confirmImport,
    clearImportPreview,
  };
}
