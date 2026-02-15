import { useState, useCallback, useEffect } from 'react';
import toast from 'react-hot-toast';
import {
  runLinearRegression,
  runMultiFactorRegression,
  runRollingRegression,
  runCompareRegression,
} from '../api/client';

export function useRegression() {
  const [mode, setMode] = useState('linear'); // linear | multi-factor | rolling | compare
  const [result, setResult] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  // Parameters
  const [asset, setAsset] = useState('');
  const [dependents, setDependents] = useState([]); // multi-factor independents
  const [compareAssets, setCompareAssets] = useState([]); // compare mode assets
  const [startDate, setStartDate] = useState(() => {
    const d = new Date();
    d.setFullYear(d.getFullYear() - 5);
    return d.toISOString().split('T')[0];
  });
  const [endDate, setEndDate] = useState(() => new Date().toISOString().split('T')[0]);
  const [windowSize, setWindowSize] = useState(30);
  const [annotations, setAnnotations] = useState([]);

  // Sidebar mode: 'standard' or 'realestate'
  const [sidebarTab, setSidebarTab] = useState('standard');

  // Clear stale result when mode changes to prevent data/chart mismatch
  useEffect(() => {
    setResult(null);
    setError(null);
  }, [mode]);

  const runAnalysis = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      let data;
      if (mode === 'linear') {
        if (!asset) { toast.error('Please select an asset'); setLoading(false); return; }
        data = await runLinearRegression(asset, startDate, endDate);
      } else if (mode === 'multi-factor') {
        if (!asset) { toast.error('Please select a dependent variable'); setLoading(false); return; }
        if (dependents.length === 0) { toast.error('Please select at least one independent variable'); setLoading(false); return; }
        data = await runMultiFactorRegression(asset, dependents, startDate, endDate);
      } else if (mode === 'rolling') {
        if (!asset) { toast.error('Please select an asset'); setLoading(false); return; }
        data = await runRollingRegression(asset, startDate, endDate, windowSize);
      } else if (mode === 'compare') {
        if (compareAssets.length < 2) { toast.error('Please select at least 2 assets to compare'); setLoading(false); return; }
        data = await runCompareRegression(compareAssets, startDate, endDate);
      }
      setResult(data);
    } catch (err) {
      const message = err.response?.data?.detail || err.message || 'Analysis failed';
      setError(message);
      toast.error(message);
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, [mode, asset, dependents, compareAssets, startDate, endDate, windowSize]);

  const addAnnotation = useCallback((annotation) => {
    setAnnotations((prev) => [...prev, annotation]);
  }, []);

  const removeAnnotation = useCallback((index) => {
    setAnnotations((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const reset = useCallback(() => {
    setMode('linear');
    setAsset('');
    setDependents([]);
    setCompareAssets([]);
    const d = new Date();
    d.setFullYear(d.getFullYear() - 5);
    setStartDate(d.toISOString().split('T')[0]);
    setEndDate(new Date().toISOString().split('T')[0]);
    setWindowSize(30);
    setAnnotations([]);
    setSidebarTab('standard');
    setResult(null);
    setError(null);
  }, []);

  const restoreParams = useCallback((config) => {
    if (config.mode) setMode(config.mode);
    if (config.asset) setAsset(config.asset);
    if (config.dependents) setDependents(config.dependents);
    if (config.compareAssets) setCompareAssets(config.compareAssets);
    if (config.startDate) setStartDate(config.startDate);
    if (config.endDate) setEndDate(config.endDate);
    if (config.windowSize) setWindowSize(config.windowSize);
    if (config.annotations) setAnnotations(config.annotations);
    if (config.sidebarTab) setSidebarTab(config.sidebarTab);
  }, []);

  const getConfig = useCallback(() => ({
    mode, asset, dependents, compareAssets, startDate, endDate, windowSize, annotations, sidebarTab,
  }), [mode, asset, dependents, compareAssets, startDate, endDate, windowSize, annotations, sidebarTab]);

  return {
    mode, setMode,
    asset, setAsset,
    dependents, setDependents,
    compareAssets, setCompareAssets,
    startDate, setStartDate,
    endDate, setEndDate,
    windowSize, setWindowSize,
    annotations, addAnnotation, removeAnnotation, setAnnotations,
    sidebarTab, setSidebarTab,
    result, loading, error,
    runAnalysis, reset, restoreParams, getConfig,
  };
}
