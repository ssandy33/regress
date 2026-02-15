import { useState } from 'react';
import { useAssetSearch } from '../../hooks/useAssetSearch';

const COLORS = ['#2563eb', '#dc2626', '#16a34a', '#f59e0b', '#8b5cf6'];

export default function ComparePicker({ assets, onChange }) {
  const { query, setQuery, results, loading } = useAssetSearch();
  const [showSearch, setShowSearch] = useState(false);

  const addAsset = (asset) => {
    if (assets.length >= 5) return;
    if (assets.includes(asset.identifier)) return;
    onChange([...assets, asset.identifier]);
    setQuery('');
    setShowSearch(false);
  };

  const removeAsset = (identifier) => {
    onChange(assets.filter((a) => a !== identifier));
  };

  return (
    <div>
      <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1.5">
        Assets to Compare ({assets.length}/5)
      </label>

      {/* Asset list */}
      <div className="space-y-1.5 mb-2">
        {assets.map((id, i) => (
          <div
            key={id}
            className="flex items-center gap-2 px-2.5 py-1.5 bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg text-sm"
          >
            <div
              className="w-3 h-3 rounded-full shrink-0"
              style={{ backgroundColor: COLORS[i] }}
            />
            <span className="flex-1 text-slate-900 dark:text-white truncate">{id}</span>
            <button
              onClick={() => removeAsset(id)}
              className="text-slate-400 hover:text-red-500 text-lg leading-none"
            >
              &times;
            </button>
          </div>
        ))}
      </div>

      {/* Add button / search */}
      {assets.length < 5 && (
        showSearch ? (
          <div className="relative">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search for an asset..."
              autoFocus
              onBlur={() => setTimeout(() => setShowSearch(false), 200)}
              className="w-full px-3 py-2 text-sm border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 focus:ring-2 focus:ring-blue-500 outline-none"
            />
            {loading && (
              <div className="absolute right-2 top-2.5">
                <svg className="w-4 h-4 animate-spin text-slate-400" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              </div>
            )}
            {query && results.length > 0 && (
              <div className="absolute z-50 w-full mt-1 max-h-48 overflow-y-auto bg-white dark:bg-slate-700 border border-slate-200 dark:border-slate-600 rounded-lg shadow-lg">
                {results.map((asset) => (
                  <button
                    key={asset.identifier}
                    onMouseDown={() => addAsset(asset)}
                    className="w-full text-left px-3 py-2 hover:bg-slate-100 dark:hover:bg-slate-600 text-sm flex justify-between"
                  >
                    <span className="text-slate-900 dark:text-white">{asset.name}</span>
                    <span className="text-xs text-slate-400">{asset.identifier}</span>
                  </button>
                ))}
              </div>
            )}
          </div>
        ) : (
          <button
            onClick={() => setShowSearch(true)}
            className="w-full py-2 border-2 border-dashed border-slate-300 dark:border-slate-600 rounded-lg text-sm text-slate-500 dark:text-slate-400 hover:border-blue-400 hover:text-blue-500 transition-colors"
          >
            + Add Asset
          </button>
        )
      )}
    </div>
  );
}

export { COLORS as COMPARE_COLORS };
