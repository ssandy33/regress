import { useState, useRef, useEffect } from 'react';
import { useAssetSearch } from '../../hooks/useAssetSearch';
import { categoryLabel } from '../../utils/formatters';

export default function AssetSelector({ value, onChange, multi = false, placeholder }) {
  const { query, setQuery, grouped, loading, recentAssets, addRecent } = useAssetSearch();
  const [open, setOpen] = useState(false);
  const wrapperRef = useRef(null);

  useEffect(() => {
    function handleClickOutside(e) {
      if (wrapperRef.current && !wrapperRef.current.contains(e.target)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  const handleSelect = (asset) => {
    addRecent(asset);
    if (multi) {
      const current = Array.isArray(value) ? value : [];
      if (!current.includes(asset.identifier)) {
        onChange([...current, asset.identifier]);
      }
    } else {
      onChange(asset.identifier);
      setQuery('');
      setOpen(false);
    }
  };

  const handleRemove = (identifier) => {
    if (multi) {
      onChange((Array.isArray(value) ? value : []).filter((v) => v !== identifier));
    } else {
      onChange('');
    }
  };

  const categoryOrder = ['indices', 'stock', 'interest_rates', 'economic_indicators', 'housing', 'commodities', 'other'];

  return (
    <div ref={wrapperRef} className="relative">
      {/* Multi-select tags */}
      {multi && Array.isArray(value) && value.length > 0 && (
        <div className="flex flex-wrap gap-1 mb-1.5">
          {value.map((v) => (
            <span
              key={v}
              className="inline-flex items-center gap-1 px-2 py-0.5 bg-blue-100 dark:bg-blue-900 text-blue-800 dark:text-blue-200 text-xs rounded-full"
            >
              {v}
              <button
                onClick={() => handleRemove(v)}
                className="hover:text-blue-600 dark:hover:text-blue-100"
              >
                &times;
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Search input */}
      <div className="relative">
        <input
          type="text"
          value={open ? query : (multi ? query : (value || query))}
          onChange={(e) => {
            setQuery(e.target.value);
            if (!multi) onChange('');
          }}
          onFocus={() => setOpen(true)}
          placeholder={placeholder}
          className="w-full px-3 py-2 text-sm border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-blue-500 focus:border-transparent outline-none"
        />
        {loading && (
          <div className="absolute right-2 top-2.5">
            <svg className="w-4 h-4 animate-spin text-slate-400" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
          </div>
        )}
      </div>

      {/* Dropdown */}
      {open && (
        <div className="absolute z-50 w-full mt-1 max-h-64 overflow-y-auto bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg shadow-lg">
          {/* Recent assets */}
          {!query && recentAssets.length > 0 && (
            <div>
              <div className="px-3 py-1.5 text-xs font-medium text-slate-400 dark:text-slate-500 uppercase">
                Recent
              </div>
              {recentAssets.map((asset) => (
                <button
                  key={asset.identifier}
                  onClick={() => handleSelect(asset)}
                  className="w-full text-left px-3 py-2 hover:bg-slate-100 dark:hover:bg-slate-600 text-sm flex items-center justify-between"
                >
                  <span className="text-slate-900 dark:text-slate-100">{asset.name}</span>
                  <span className="text-xs text-slate-400">{asset.identifier}</span>
                </button>
              ))}
            </div>
          )}

          {/* Grouped search results */}
          {query && categoryOrder.map((cat) => {
            const items = grouped[cat];
            if (!items || items.length === 0) return null;
            return (
              <div key={cat}>
                <div className="px-3 py-1.5 text-xs font-medium text-slate-400 dark:text-slate-500 uppercase">
                  {categoryLabel(cat)}
                </div>
                {items.map((asset) => (
                  <button
                    key={asset.identifier}
                    onClick={() => handleSelect(asset)}
                    className="w-full text-left px-3 py-2 hover:bg-slate-100 dark:hover:bg-slate-600 text-sm flex items-center justify-between"
                  >
                    <span className="text-slate-900 dark:text-slate-100">{asset.name}</span>
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-slate-400">{asset.identifier}</span>
                      <span className="text-[10px] px-1.5 py-0.5 rounded bg-slate-100 dark:bg-slate-600 text-slate-500 dark:text-slate-400">
                        {asset.source}
                      </span>
                    </div>
                  </button>
                ))}
              </div>
            );
          })}

          {query && Object.keys(grouped).length === 0 && !loading && (
            <div className="px-3 py-4 text-sm text-slate-400 text-center">
              No results found
            </div>
          )}
        </div>
      )}
    </div>
  );
}
