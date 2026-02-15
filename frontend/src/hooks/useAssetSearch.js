import { useState, useEffect, useRef, useCallback } from 'react';
import { searchAssets } from '../api/client';
import { useOffline } from '../context/OfflineContext';

const RECENT_KEY = 'recentAssets';
const MAX_RECENT = 5;

export function useAssetSearch() {
  const { allDown } = useOffline();
  const [query, setQuery] = useState('');
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [recentAssets, setRecentAssets] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem(RECENT_KEY)) || [];
    } catch {
      return [];
    }
  });
  const debounceRef = useRef(null);

  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      return;
    }

    if (debounceRef.current) clearTimeout(debounceRef.current);

    debounceRef.current = setTimeout(async () => {
      setLoading(true);
      try {
        const res = await searchAssets(query, allDown);
        setResults(res);
      } catch {
        setResults([]);
      } finally {
        setLoading(false);
      }
    }, 300);

    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, [query, allDown]);

  const addRecent = useCallback((asset) => {
    setRecentAssets((prev) => {
      const filtered = prev.filter((a) => a.identifier !== asset.identifier);
      const updated = [asset, ...filtered].slice(0, MAX_RECENT);
      localStorage.setItem(RECENT_KEY, JSON.stringify(updated));
      return updated;
    });
  }, []);

  // Group results by category
  const grouped = results.reduce((acc, asset) => {
    const cat = asset.category || 'other';
    if (!acc[cat]) acc[cat] = [];
    acc[cat].push(asset);
    return acc;
  }, {});

  return { query, setQuery, results, grouped, loading, recentAssets, addRecent };
}
