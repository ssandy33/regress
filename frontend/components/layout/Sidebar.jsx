import { useState } from 'react';
import AssetSelector from '../controls/AssetSelector';
import ComparePicker from '../controls/ComparePicker';
import DateRangePicker from '../controls/DateRangePicker';
import RealEstateSelector from '../controls/RealEstateSelector';
import WindowSizeSlider from '../controls/WindowSizeSlider';

export default function Sidebar({
  mode,
  asset, setAsset,
  dependents, setDependents,
  compareAssets, setCompareAssets,
  startDate, setStartDate,
  endDate, setEndDate,
  windowSize, setWindowSize,
  sidebarTab, setSidebarTab,
  showEarnings, setShowEarnings,
  onRun, loading,
  onSave, onReset,
}) {
  const [collapsed, setCollapsed] = useState(false);

  if (collapsed) {
    return (
      <div className="w-12 border-r border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 flex flex-col items-center pt-3">
        <button
          onClick={() => setCollapsed(false)}
          className="p-2 rounded hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-600 dark:text-slate-300"
          aria-label="Expand sidebar"
        >
          <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 5l7 7-7 7M5 5l7 7-7 7" />
          </svg>
        </button>
      </div>
    );
  }

  return (
    <aside className="w-80 border-r border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800 flex flex-col shrink-0 overflow-y-auto">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-200 dark:border-slate-700">
        <span className="text-sm font-medium text-slate-700 dark:text-slate-200">Parameters</span>
        <button
          onClick={() => setCollapsed(true)}
          className="p-1 rounded hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-500 dark:text-slate-400"
          aria-label="Collapse sidebar"
        >
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 19l-7-7 7-7m8 14l-7-7 7-7" />
          </svg>
        </button>
      </div>

      <div className="p-4 space-y-5 flex-1">
        {/* Asset Selection — depends on mode and sidebar tab */}
        {mode === 'compare' ? (
          <ComparePicker assets={compareAssets} onChange={setCompareAssets} />
        ) : sidebarTab === 'realestate' ? (
          <RealEstateSelector
            asset={asset}
            onAssetChange={setAsset}
            onBack={() => setSidebarTab('standard')}
          />
        ) : (
          <>
            <div>
              <div className="flex items-center justify-between mb-1.5">
                <label className="text-xs font-medium text-slate-500 dark:text-slate-400">
                  {mode === 'multi-factor' ? 'Dependent Variable' : 'Asset'}
                </label>
                <button
                  onClick={() => setSidebarTab('realestate')}
                  className="text-xs text-blue-600 hover:text-blue-700 dark:text-blue-400"
                >
                  Real Estate
                </button>
              </div>
              <AssetSelector
                value={asset}
                onChange={setAsset}
                placeholder="Search assets..."
              />
            </div>

            {/* Multi-factor independents */}
            {mode === 'multi-factor' && (
              <div>
                <label className="block text-xs font-medium text-slate-500 dark:text-slate-400 mb-1.5">
                  Independent Variables
                </label>
                <AssetSelector
                  value={dependents}
                  onChange={setDependents}
                  multi
                  placeholder="Add factors..."
                />
              </div>
            )}
          </>
        )}

        {/* Date Range */}
        <DateRangePicker
          startDate={startDate}
          endDate={endDate}
          onStartChange={setStartDate}
          onEndChange={setEndDate}
        />

        {/* Window Size (rolling only) */}
        {mode === 'rolling' && (
          <WindowSizeSlider value={windowSize} onChange={setWindowSize} />
        )}

        {/* Earnings overlay (linear mode only) */}
        {mode === 'linear' && (
          <label className="flex items-center gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={showEarnings}
              onChange={(e) => setShowEarnings(e.target.checked)}
              className="rounded border-slate-300 dark:border-slate-600 text-blue-600 focus:ring-blue-500"
            />
            <span className="text-xs font-medium text-slate-500 dark:text-slate-400">
              Show Earnings Dates
            </span>
          </label>
        )}
      </div>

      {/* Action buttons */}
      <div className="p-4 border-t border-slate-200 dark:border-slate-700 space-y-2">
        <button
          onClick={onRun}
          disabled={loading}
          className="w-full py-2 px-4 bg-blue-600 hover:bg-blue-700 disabled:bg-blue-400 text-white rounded-lg text-sm font-medium transition-colors flex items-center justify-center gap-2"
        >
          {loading ? (
            <>
              <svg className="w-4 h-4 animate-spin" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Running...
            </>
          ) : (
            'Run Analysis'
          )}
        </button>
        <div className="flex gap-2">
          <button
            onClick={onSave}
            className="flex-1 py-2 px-4 border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-200 rounded-lg text-sm font-medium hover:bg-slate-100 dark:hover:bg-slate-700 transition-colors"
          >
            Save
          </button>
          <button
            onClick={onReset}
            className="flex-1 py-2 px-4 border border-red-300 dark:border-red-700 text-red-600 dark:text-red-400 rounded-lg text-sm font-medium hover:bg-red-50 dark:hover:bg-red-900/30 transition-colors"
          >
            Reset
          </button>
        </div>
      </div>
    </aside>
  );
}
