import { useState, useEffect } from 'react';
import Link from 'next/link';
import toast from 'react-hot-toast';
import {
  getSettings, updateSetting, getCacheStats, clearCache, checkFredHealth,
  checkSchwabHealth, checkSourceHealth, getBackups, restoreBackup, getCacheFreshness,
  refreshAllCache, refreshStaleCache,
} from '../../api/client';
import { formatNumber } from '../../utils/formatters';

function freshnessColor(freshness) {
  if (freshness === 'fresh') return 'text-green-700 dark:text-green-300 bg-green-50 dark:bg-green-900/30';
  if (freshness === 'stale') return 'text-orange-700 dark:text-orange-300 bg-orange-50 dark:bg-orange-900/30';
  return 'text-red-700 dark:text-red-300 bg-red-50 dark:bg-red-900/30';
}

function statusDot(available) {
  return available
    ? 'bg-green-400'
    : 'bg-red-400';
}

export default function SettingsPage() {
  const [settings, setSettings] = useState(null);
  const [cacheStats, setCacheStats] = useState(null);
  const [fredKey, setFredKey] = useState('');
  const [fredStatus, setFredStatus] = useState(null);
  const [loading, setLoading] = useState(true);
  const [sourceHealth, setSourceHealth] = useState(null);
  const [backups, setBackups] = useState([]);
  const [freshness, setFreshness] = useState([]);
  const [refreshing, setRefreshing] = useState(false);
  const [restoring, setRestoring] = useState(null);
  const [schwabStatus, setSchwabStatus] = useState(null);
  const [schwabTesting, setSchwabTesting] = useState(false);

  useEffect(() => {
    Promise.all([
      getSettings(),
      getCacheStats(),
      checkFredHealth(),
      checkSourceHealth().catch(() => null),
      getBackups().catch(() => []),
      getCacheFreshness().catch(() => []),
    ])
      .then(([s, c, f, h, b, fr]) => {
        setSettings(s);
        setCacheStats(c);
        setFredStatus(f);
        setSourceHealth(h);
        setBackups(b || []);
        setFreshness(fr || []);
      })
      .catch(() => toast.error('Failed to load settings'))
      .finally(() => setLoading(false));
  }, []);

  const handleSaveFredKey = async () => {
    if (!fredKey.trim()) return;
    try {
      await updateSetting('fred_api_key', fredKey.trim());
      toast.success('FRED API key saved');
      setFredKey('');
      const f = await checkFredHealth();
      setFredStatus(f);
      const s = await getSettings();
      setSettings(s);
    } catch {
      toast.error('Failed to save API key');
    }
  };

  const handleClearCache = async () => {
    try {
      await clearCache();
      toast.success('Cache cleared');
      const [c, fr] = await Promise.all([getCacheStats(), getCacheFreshness().catch(() => [])]);
      setCacheStats(c);
      setFreshness(fr || []);
    } catch {
      toast.error('Failed to clear cache');
    }
  };

  const handleRefreshAll = async () => {
    setRefreshing(true);
    try {
      const results = await refreshAllCache();
      const ok = results.filter(r => r.status === 'refreshed').length;
      const fail = results.filter(r => r.status === 'failed').length;
      toast.success(`Refreshed ${ok} assets${fail ? `, ${fail} failed` : ''}`);
      const [c, fr] = await Promise.all([getCacheStats(), getCacheFreshness().catch(() => [])]);
      setCacheStats(c);
      setFreshness(fr || []);
    } catch {
      toast.error('Failed to refresh cache');
    } finally {
      setRefreshing(false);
    }
  };

  const handleRefreshStale = async () => {
    setRefreshing(true);
    try {
      const results = await refreshStaleCache();
      if (results.length === 0) {
        toast.success('All data is fresh, nothing to refresh');
      } else {
        const ok = results.filter(r => r.status === 'refreshed').length;
        toast.success(`Refreshed ${ok} stale assets`);
      }
      const [c, fr] = await Promise.all([getCacheStats(), getCacheFreshness().catch(() => [])]);
      setCacheStats(c);
      setFreshness(fr || []);
    } catch {
      toast.error('Failed to refresh stale cache');
    } finally {
      setRefreshing(false);
    }
  };

  const handleRestore = async (filename) => {
    if (!confirm(`Restore database from ${filename}? This will replace the current database.`)) return;
    setRestoring(filename);
    try {
      await restoreBackup(filename);
      toast.success(`Restored from ${filename}`);
      const [c, fr] = await Promise.all([getCacheStats(), getCacheFreshness().catch(() => [])]);
      setCacheStats(c);
      setFreshness(fr || []);
    } catch {
      toast.error('Failed to restore backup');
    } finally {
      setRestoring(null);
    }
  };

  const handleUpdateSetting = async (key, value) => {
    try {
      await updateSetting(key, String(value));
      toast.success('Setting updated');
      const s = await getSettings();
      setSettings(s);
    } catch {
      toast.error('Failed to update setting');
    }
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-white dark:bg-slate-900 flex items-center justify-center">
        <svg className="w-8 h-8 animate-spin text-blue-600" viewBox="0 0 24 24" fill="none">
          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
        </svg>
      </div>
    );
  }

  const cacheSizeKB = cacheStats ? (cacheStats.total_size_bytes / 1024).toFixed(1) : 0;

  return (
    <div className="min-h-screen bg-white dark:bg-slate-900">
      <div className="max-w-2xl mx-auto px-6 py-8">
        {/* Header */}
        <div className="flex items-center justify-between mb-8">
          <h1 className="text-2xl font-bold text-slate-900 dark:text-white">Settings</h1>
          <Link
            href="/"
            className="text-sm text-blue-600 hover:text-blue-700 dark:text-blue-400"
          >
            Back to Analysis
          </Link>
        </div>

        <div className="space-y-8">
          {/* Data Source Status */}
          <section className="bg-slate-50 dark:bg-slate-800 rounded-xl p-6 border border-slate-200 dark:border-slate-700">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-4">Data Source Status</h2>
            <div className="space-y-3">
              {['yfinance', 'fred', 'zillow'].map((source) => {
                const info = sourceHealth?.[source];
                return (
                  <div key={source} className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className={`w-2.5 h-2.5 rounded-full ${info ? statusDot(info.available) : 'bg-slate-300'}`} />
                      <span className="text-sm font-medium text-slate-700 dark:text-slate-300 capitalize">
                        {source === 'yfinance' ? 'Yahoo Finance' : source === 'fred' ? 'FRED' : 'Zillow'}
                      </span>
                    </div>
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                      {info ? (info.available ? 'Online' : info.error || 'Unavailable') : 'Unknown'}
                    </span>
                  </div>
                );
              })}
            </div>
          </section>

          {/* FRED API Key */}
          <section className="bg-slate-50 dark:bg-slate-800 rounded-xl p-6 border border-slate-200 dark:border-slate-700">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-1">FRED API Key</h2>
            <p className="text-sm text-slate-500 dark:text-slate-400 mb-4">
              Required for interest rate and housing data from the Federal Reserve.
            </p>

            <div className="flex items-center gap-2 mb-3">
              <span className={`w-2 h-2 rounded-full ${
                fredStatus?.valid ? 'bg-green-400' : fredStatus?.configured ? 'bg-yellow-400' : 'bg-red-400'
              }`} />
              <span className="text-sm text-slate-700 dark:text-slate-300">
                {fredStatus?.valid ? 'Connected and working' : fredStatus?.configured ? 'Key set but validation failed' : 'Not configured'}
              </span>
            </div>

            <div className="flex gap-2">
              <input
                type="password"
                value={fredKey}
                onChange={(e) => setFredKey(e.target.value)}
                placeholder={settings?.fred_api_key_set ? 'Key is set (enter new to replace)' : 'Enter your FRED API key'}
                className="flex-1 px-3 py-2 text-sm border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100 outline-none focus:ring-2 focus:ring-blue-500"
              />
              <button
                onClick={handleSaveFredKey}
                disabled={!fredKey.trim()}
                className="px-4 py-2 text-sm bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:bg-blue-400"
              >
                Save
              </button>
            </div>

            {!fredStatus?.configured && (
              <p className="text-xs text-slate-400 mt-2">
                Get a free key at{' '}
                <a href="https://fred.stlouisfed.org/docs/api/api_key.html" target="_blank" rel="noopener noreferrer" className="text-blue-500 underline">
                  fred.stlouisfed.org
                </a>
              </p>
            )}
          </section>

          {/* Schwab API */}
          <section className="bg-slate-50 dark:bg-slate-800 rounded-xl p-6 border border-slate-200 dark:border-slate-700">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-1">Schwab API</h2>
            <p className="text-sm text-slate-500 dark:text-slate-400 mb-4">
              OAuth 2.0 connection for Schwab market data.
            </p>

            <div className="flex items-center gap-2 mb-3">
              <span className={`w-2 h-2 rounded-full ${
                settings?.schwab_configured ? 'bg-green-400' : 'bg-red-400'
              }`} />
              <span className="text-sm text-slate-700 dark:text-slate-300">
                {settings?.schwab_configured ? 'Configured' : 'Not configured'}
              </span>
            </div>

            {settings?.schwab_configured ? (
              <div className="space-y-3">
                {settings.schwab_token_expires && (
                  <p className="text-xs text-slate-500 dark:text-slate-400">
                    Refresh token expires: {new Date(settings.schwab_token_expires).toLocaleString()}
                  </p>
                )}
                <button
                  onClick={async () => {
                    setSchwabTesting(true);
                    try {
                      const result = await checkSchwabHealth();
                      setSchwabStatus(result);
                      if (result.valid) {
                        toast.success('Schwab connection is working');
                      } else {
                        toast.error(result.error || 'Schwab connection test failed');
                      }
                    } catch {
                      toast.error('Failed to test Schwab connection');
                    } finally {
                      setSchwabTesting(false);
                    }
                  }}
                  disabled={schwabTesting}
                  className="px-4 py-2 text-sm border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-600 disabled:opacity-50"
                >
                  {schwabTesting ? 'Testing...' : 'Test Connection'}
                </button>
                {schwabStatus && (
                  <div className="flex items-center gap-2 mt-2">
                    <span className={`w-2 h-2 rounded-full ${schwabStatus.valid ? 'bg-green-400' : 'bg-red-400'}`} />
                    <span className="text-xs text-slate-500 dark:text-slate-400">
                      {schwabStatus.valid ? 'Connection verified' : schwabStatus.error || 'Verification failed'}
                    </span>
                  </div>
                )}
              </div>
            ) : (
              <div className="bg-white dark:bg-slate-700 rounded-lg border border-slate-200 dark:border-slate-600 p-4">
                <p className="text-sm text-slate-600 dark:text-slate-300 mb-2">
                  To connect, run the authorization CLI command:
                </p>
                <code className="block text-xs bg-slate-100 dark:bg-slate-800 px-3 py-2 rounded text-slate-800 dark:text-slate-200">
                  cd backend && python -m app.cli schwab-auth
                </code>
              </div>
            )}
          </section>

          {/* Data Freshness Dashboard */}
          <section className="bg-slate-50 dark:bg-slate-800 rounded-xl p-6 border border-slate-200 dark:border-slate-700">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-lg font-semibold text-slate-900 dark:text-white">Data Freshness</h2>
                <p className="text-sm text-slate-500 dark:text-slate-400">Age and freshness of cached datasets.</p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={handleRefreshStale}
                  disabled={refreshing}
                  className="px-3 py-1.5 text-xs border border-orange-300 dark:border-orange-700 text-orange-600 dark:text-orange-400 rounded-lg hover:bg-orange-50 dark:hover:bg-orange-900/20 disabled:opacity-50"
                >
                  {refreshing ? 'Refreshing...' : 'Refresh Stale'}
                </button>
                <button
                  onClick={handleRefreshAll}
                  disabled={refreshing}
                  className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                >
                  Refresh All
                </button>
              </div>
            </div>

            {freshness.length === 0 ? (
              <p className="text-sm text-slate-400">No cached data.</p>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-slate-200 dark:border-slate-700">
                      <th className="text-left px-3 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">Asset</th>
                      <th className="text-left px-3 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">Source</th>
                      <th className="text-right px-3 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">Age</th>
                      <th className="text-right px-3 py-2 text-xs font-medium text-slate-500 dark:text-slate-400">Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {freshness.map((entry) => (
                      <tr key={entry.asset_key} className={`border-b border-slate-100 dark:border-slate-700/50 ${entry.freshness === 'very_stale' ? 'bg-red-50/50 dark:bg-red-900/10' : entry.freshness === 'stale' ? 'bg-orange-50/50 dark:bg-orange-900/10' : ''}`}>
                        <td className="px-3 py-2 font-medium text-slate-900 dark:text-white truncate max-w-[200px]">{entry.asset_key}</td>
                        <td className="px-3 py-2 text-slate-600 dark:text-slate-400">{entry.source}</td>
                        <td className="px-3 py-2 text-right text-slate-600 dark:text-slate-400">{entry.age_days}d</td>
                        <td className="px-3 py-2 text-right">
                          <span className={`text-xs px-2 py-0.5 rounded-full ${freshnessColor(entry.freshness)}`}>
                            {entry.freshness === 'very_stale' ? 'Very Stale' : entry.freshness === 'stale' ? 'Stale' : 'Fresh'}
                          </span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </section>

          {/* Cache Management */}
          <section className="bg-slate-50 dark:bg-slate-800 rounded-xl p-6 border border-slate-200 dark:border-slate-700">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-1">Cache</h2>
            <p className="text-sm text-slate-500 dark:text-slate-400 mb-4">
              Cached data reduces API calls and speeds up analysis.
            </p>

            <div className="grid grid-cols-2 gap-4 mb-4">
              <div>
                <div className="text-2xl font-bold text-slate-900 dark:text-white">{cacheStats?.entry_count || 0}</div>
                <div className="text-xs text-slate-500">Cached datasets</div>
              </div>
              <div>
                <div className="text-2xl font-bold text-slate-900 dark:text-white">{cacheSizeKB} KB</div>
                <div className="text-xs text-slate-500">Total size</div>
              </div>
            </div>

            <button
              onClick={handleClearCache}
              className="px-4 py-2 text-sm border border-red-300 dark:border-red-700 text-red-600 dark:text-red-400 rounded-lg hover:bg-red-50 dark:hover:bg-red-900/20"
            >
              Clear All Cache
            </button>
          </section>

          {/* Database Backups */}
          <section className="bg-slate-50 dark:bg-slate-800 rounded-xl p-6 border border-slate-200 dark:border-slate-700">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-1">Database Backups</h2>
            <p className="text-sm text-slate-500 dark:text-slate-400 mb-4">
              Automatic backups are created on each server start. Restore to a previous state if needed.
            </p>

            {backups.length === 0 ? (
              <p className="text-sm text-slate-400">No backups available.</p>
            ) : (
              <div className="space-y-2">
                {backups.map((b) => (
                  <div key={b.filename} className="flex items-center justify-between px-3 py-2 bg-white dark:bg-slate-700 rounded-lg border border-slate-200 dark:border-slate-600">
                    <div>
                      <div className="text-sm font-medium text-slate-900 dark:text-white">{b.filename}</div>
                      <div className="text-xs text-slate-500 dark:text-slate-400">
                        {new Date(b.created_at).toLocaleString()} &middot; {(b.size_bytes / 1024).toFixed(1)} KB
                      </div>
                    </div>
                    <button
                      onClick={() => handleRestore(b.filename)}
                      disabled={restoring === b.filename}
                      className="px-3 py-1 text-xs border border-slate-300 dark:border-slate-600 text-slate-700 dark:text-slate-300 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-600 disabled:opacity-50"
                    >
                      {restoring === b.filename ? 'Restoring...' : 'Restore'}
                    </button>
                  </div>
                ))}
              </div>
            )}
          </section>

          {/* Preferences */}
          <section className="bg-slate-50 dark:bg-slate-800 rounded-xl p-6 border border-slate-200 dark:border-slate-700">
            <h2 className="text-lg font-semibold text-slate-900 dark:text-white mb-4">Preferences</h2>

            <div className="space-y-4">
              <div>
                <label className="block text-sm text-slate-700 dark:text-slate-300 mb-1">Default Date Range</label>
                <select
                  value={settings?.default_date_range_years || 5}
                  onChange={(e) => handleUpdateSetting('default_date_range_years', e.target.value)}
                  className="w-full px-3 py-2 text-sm border border-slate-300 dark:border-slate-600 rounded-lg bg-white dark:bg-slate-700 text-slate-900 dark:text-slate-100"
                >
                  <option value="1">1 Year</option>
                  <option value="3">3 Years</option>
                  <option value="5">5 Years</option>
                  <option value="10">10 Years</option>
                </select>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
